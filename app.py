import streamlit as st
import os
import re
import psycopg2
import json
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from seed_data import ESTRUTURA_ASSUNTOS

SUPABASE_URL = st.secrets["SUPABASE_URL"]

# -- CONFIGURAÇÃO DA PÁGINA --
st.set_page_config(
    page_title="Gerador de Questões SEDES DF",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

def init_db():
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS assuntos (id INTEGER PRIMARY KEY AUTOINCREMENT, categoria_id INTEGER, nome TEXT UNIQUE, pdf_path TEXT, start_page INTEGER, end_page INTEGER, FOREIGN KEY(categoria_id) REFERENCES categorias(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS questoes (id INTEGER PRIMARY KEY AUTOINCREMENT, assunto_id INTEGER, enunciado TEXT, alternativas TEXT, resposta_correta TEXT, explicacoes TEXT, FOREIGN KEY(assunto_id) REFERENCES assuntos(id))''')
    
    # Criar tabela de usuários se não existir
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT UNIQUE, senha TEXT)''')
    c.execute("INSERT INTO usuarios (id, login, senha) VALUES (1, 'vitor', '@19216801Gg')")
    c.execute("INSERT INTO usuarios (id, login, senha) VALUES (2, 'gabi', 'jlsp2000')")
    
    # Tabela de respostas (agora com usuario_id)
    c.execute('''CREATE TABLE IF NOT EXISTS respostas (id INTEGER PRIMARY KEY AUTOINCREMENT, questao_id INTEGER, resposta_dada TEXT, correta BOOLEAN, usuario_id INTEGER, FOREIGN KEY(questao_id) REFERENCES questoes(id), FOREIGN KEY(usuario_id) REFERENCES usuarios(id))''')
    
    for cat_nome, assuntos in ESTRUTURA_ASSUNTOS.items():
        c.execute("INSERT INTO categorias (nome) VALUES (%s)", (cat_nome,))
        c.execute("SELECT id FROM categorias WHERE nome = %s", (cat_nome,))
        cat_id = c.fetchone()[0]
        for ass in assuntos:
            c.execute("""
                INSERT INTO assuntos (categoria_id, nome, pdf_path, start_page, end_page)
                VALUES (?, ?, ?, ?, ?)
            """, (cat_id, ass["nome"], ass.get("pdf"), ass.get("start"), ass.get("end")))
            
    conn.commit()
    c.close()
    conn.close()

# init_db()  # DB já populado no Supabase

def login_user(login, senha):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("SELECT id, login FROM usuarios WHERE login = %s AND senha = %s", (login, senha))
    user = c.fetchone()
    c.close()
    conn.close()
    return user

def get_categorias():
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("SELECT id, nome FROM categorias")
    res = c.fetchall()
    conn.close()
    return [{"id": r[0], "nome": r[1]} for r in res]

def get_assuntos(categoria_id=None):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    if categoria_id:
        c.execute("SELECT id, nome, pdf_path, start_page, end_page FROM assuntos WHERE categoria_id = %s", (categoria_id,))
    else:
        c.execute("SELECT id, nome, pdf_path, start_page, end_page FROM assuntos")
    res = c.fetchall()
    conn.close()
    return [{"id": r[0], "nome": r[1], "pdf": r[2], "start": r[3], "end": r[4]} for r in res]

def get_dashboard_stats(categoria_id, usuario_id):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    query = '''
        SELECT a.id, a.nome,
               COUNT(DISTINCT q.id) as total_questoes,
               COUNT(DISTINCT r.questao_id) as total_respondidas,
               SUM(CASE WHEN r.correta = TRUE THEN 1 ELSE 0 END) as total_acertos
        FROM assuntos a
        LEFT JOIN questoes q ON a.id = q.assunto_id
        LEFT JOIN respostas r ON q.id = r.questao_id AND r.usuario_id = %s
        WHERE a.categoria_id = %s
        GROUP BY a.id
    '''
    c.execute(query, (usuario_id, categoria_id))
    stats = c.fetchall()
    conn.close()
    
    res = []
    for row in stats:
        res.append({
            "id": row[0],
            "nome": row[1],
            "total": row[2],
            "respondidas": row[3],
            "acertos": row[4] if row[4] else 0
        })
    return res

def salvar_questoes_db(assunto_id, questoes_list):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    for q in questoes_list:
        c.execute("""
            INSERT INTO questoes (assunto_id, enunciado, alternativas, resposta_correta, explicacoes)
            VALUES (?, ?, ?, ?, ?)
        """, (assunto_id, q["enunciado"], json.dumps(q["alternativas"]), q["resposta_correta"], json.dumps(q.get("explicacoes_opcoes", {}))))
    conn.commit()
    conn.close()

def get_proxima_questao(assunto_id, usuario_id):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    query = """
        SELECT id, enunciado, alternativas, resposta_correta, explicacoes
        FROM questoes
        WHERE assunto_id = %s AND id NOT IN (SELECT questao_id FROM respostas WHERE usuario_id = %s)
        LIMIT 1
    """
    c.execute(query, (assunto_id, usuario_id))
    row = c.fetchone()
    conn.close()
    
    if row:
        alts_brutas = json.loads(row[2])
        letras = ["A", "B", "C", "D", "E"]
        alts_formatadas = []
        for i, alt in enumerate(alts_brutas):
            if i < len(letras):
                if alt.startswith(letras[i] + ")") or alt.startswith(letras[i] + " -") or alt.startswith(letras[i] + "."):
                    alts_formatadas.append(alt)
                else:
                    alts_formatadas.append(f"{letras[i]}) {alt}")
            else:
                alts_formatadas.append(alt)
                
        return {
            "id": row[0],
            "enunciado": row[1],
            "alternativas": alts_formatadas,
            "resposta_correta": row[3].strip().upper()[0] if row[3] else "A",
            "explicacoes_opcoes": json.loads(row[4])
        }
    return None

def salvar_resposta(questao_id, resposta_dada, correta, usuario_id):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("INSERT INTO respostas (questao_id, resposta_dada, correta, usuario_id) VALUES (%s, %s, %s, %s)", 
              (questao_id, resposta_dada, correta, usuario_id))
    conn.commit()
    conn.close()

def resetar_progresso_assunto(assunto_id, usuario_id):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("""
        DELETE FROM respostas 
        WHERE usuario_id = %s 
        AND questao_id IN (SELECT id FROM questoes WHERE assunto_id = %s)
    """, (usuario_id, assunto_id))
    conn.commit()
    conn.close()

def get_nome_assunto(assunto_id):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("SELECT nome FROM assuntos WHERE id = %s", (assunto_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else "Assunto"

def get_todas_questoes(assunto_id):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("SELECT id, enunciado, alternativas, resposta_correta, explicacoes FROM questoes WHERE assunto_id = %s ORDER BY id", (assunto_id,))
    res = c.fetchall()
    conn.close()
    
    lista = []
    for r in res:
        lista.append({
            "id": r[0],
            "enunciado": r[1],
            "alternativas": json.loads(r[2]),
            "resposta_correta": r[3],
            "explicacoes_opcoes": json.loads(r[4])
        })
    return lista

def atualizar_questao(questao_id, enunciado, alternativas, correta, explicacoes):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("""
        UPDATE questoes 
        SET enunciado = %s, alternativas = %s, resposta_correta = %s, explicacoes = %s
        WHERE id = %s
    """, (enunciado, json.dumps(alternativas), correta, json.dumps(explicacoes), questao_id))
    conn.commit()
    conn.close()

def deletar_questao(questao_id):
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("DELETE FROM respostas WHERE questao_id = %s", (questao_id,))
    c.execute("DELETE FROM questoes WHERE id = %s", (questao_id,))
    conn.commit()
    conn.close()

# -- ESTILIZAÇÃO LIGHT THEME (CSS) --
def load_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        :root {
            --bg-color: #0f172a;
            --surface-color: #1e293b;
            --border-color: rgba(255, 255, 255, 0.05);
            --accent-color: #3b82f6;
            --accent-hover: #60a5fa;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --success-bg: rgba(16, 185, 129, 0.1);
            --success-text: #34d399;
            --error-bg: rgba(239, 68, 68, 0.1);
            --error-text: #f87171;
            --neutral-bg: #334155;
        }

        .stApp { background-color: var(--bg-color); color: var(--text-main); font-family: 'Inter', sans-serif; }
        .block-container { padding-top: 2rem !important; }
        .stMarkdown, .stText, h1, h2, h3, h4, p, span { color: var(--text-main) !important; }

        [data-testid="stSidebar"] {
            background-color: var(--surface-color) !important;
            border-right: 1px solid var(--border-color);
        }

        .question-card {
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 32px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }

        .question-text { font-size: 1.2rem; font-weight: 600; margin-bottom: 24px; line-height: 1.6; }

        .stButton>button {
            background: linear-gradient(135deg, #3b82f6, #2563eb);
            color: white !important;
            border: none;
            border-radius: 8px;
            padding: 0.6rem 1.2rem;
            font-weight: 600;
            transition: all 0.3s ease;
            width: 100%;
            box-shadow: 0 4px 10px rgba(59, 130, 246, 0.3);
        }
        .stButton>button:hover { 
            transform: translateY(-2px);
            box-shadow: 0 6px 15px rgba(59, 130, 246, 0.4);
        }

        .alt-container { border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; margin-bottom: 16px; background-color: var(--surface-color); transition: all 0.2s ease; }
        .alt-container:hover { border-color: rgba(255, 255, 255, 0.15); }
        .alt-correct { background-color: var(--success-bg); border-color: #10b981; }
        .alt-incorrect { background-color: var(--error-bg); border-color: #ef4444; }
        .alt-neutral { background-color: var(--surface-color); }
        .alt-text { font-weight: 600; margin-bottom: 8px; color: var(--text-main); }
        .alt-explanation { font-size: 0.9rem; color: var(--text-muted); line-height: 1.5; }

        .app-header {
            text-align: center;
            padding: 2rem 0;
            margin-bottom: 2rem;
            background: linear-gradient(145deg, #1e293b, #0f172a);
            border-radius: 16px;
            border: 1px solid var(--border-color);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }
        .app-header h1 {
            background: -webkit-linear-gradient(45deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-size: 2.5rem; margin-bottom: 0.5rem; font-weight: 800;
        }
        
        .dash-card {
            background: var(--surface-color);
            border-radius: 16px;
            padding: 24px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.02);
            box-shadow: 0 8px 20px rgba(0,0,0,0.2);
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .dash-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 30px rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.05);
        }
        
        .login-box {
            max-width: 400px;
            margin: 100px auto;
            background: var(--surface-color);
            padding: 40px;
            border-radius: 16px;
            border: 1px solid var(--border-color);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
        }
        </style>
    """, unsafe_allow_html=True)

def render_svg_chart(assunto_nome, total, respondidas, acertos):
    progresso = respondidas / total if total > 0 else 0
    acuracia = acertos / respondidas if respondidas > 0 else 0
    
    circ_ext = 565.48
    circ_int = 439.82
    offset_ext = circ_ext * (1 - progresso)
    offset_int = circ_int * (1 - acuracia)
    
    # O Título agora fica fora do círculo (em HTML) para não cortar e poder quebrar linha
    title_html = f"<div style='font-size: 0.95rem; font-weight: 600; color: #f8fafc; margin-bottom: 15px; min-height: 45px; display: flex; align-items: center; justify-content: center;'>{assunto_nome}</div>"
    
    svg_html = f"""<div style="display: flex; justify-content: center; margin-bottom: 10px;">
<svg width="200" height="200" viewBox="0 0 200 200">
  <circle cx="100" cy="100" r="90" fill="none" stroke="#334155" stroke-width="12"/>
  <circle cx="100" cy="100" r="70" fill="none" stroke="#334155" stroke-width="12"/>
  <circle cx="100" cy="100" r="90" fill="none" stroke="#3b82f6" stroke-width="12" stroke-dasharray="{circ_ext}" stroke-dashoffset="{offset_ext}" stroke-linecap="round" transform="rotate(-90 100 100)"/>
  <circle cx="100" cy="100" r="70" fill="none" stroke="#10b981" stroke-width="12" stroke-dasharray="{circ_int}" stroke-dashoffset="{offset_int}" stroke-linecap="round" transform="rotate(-90 100 100)"/>
  <text x="100" y="95" font-family="Inter" font-size="28" font-weight="bold" fill="#10b981" text-anchor="middle">{int(acuracia*100)}%</text>
  <text x="100" y="115" font-family="Inter" font-size="12" fill="#94a3b8" text-anchor="middle">Acertos</text>
  <text x="100" y="140" font-family="Inter" font-size="12" font-weight="bold" fill="#60a5fa" text-anchor="middle">{respondidas} / {total} Feitas</text>
</svg>
</div>"""
    return title_html + svg_html

# -- IA E PDF SMART SEARCH --
def extrair_texto_smart(pdf_path, start_page, end_page):
    try:
        doc = fitz.open(pdf_path)
        total = len(doc)
        if total == 0: return ""
        s = max(0, start_page - 1)
        e = min(total - 1, end_page + 1)
        texto = ""
        for p in range(s, e + 1):
            texto += doc.load_page(p).get_text("text") + "\\n"
        limite_chars = 300000
        return texto[:limite_chars]
    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return ""

def gerar_questoes_ia(api_key, texto_base, assunto, num_questoes, modo_sem_pdf=False):
    client = genai.Client(api_key=api_key)
    
    regras = f"""
    REGRAS CRÍTICAS DE GERAÇÃO:
    1. Você pode criar questões pedindo a alternativa CORRETA ou a INCORRETA (exceção).
    2. IMPORTANTE: Se o enunciado pedir a alternativa INCORRETA, o campo 'resposta_correta' no JSON deve OBRIGATORIAMENTE conter a letra (A, B, C, D ou E) dessa alternativa incorreta. O sistema usa este campo para validar o clique do aluno.
    3. Cada questão deve ter exatamente 5 alternativas (A, B, C, D, E).
    """

    if modo_sem_pdf:
        prompt = f"""Você é um especialista em Concursos Públicos da banca Quadrix. Elabore {num_questoes} questões inéditas sobre o assunto: "{assunto}". {regras}"""
        conteudo = [prompt]
    else:
        prompt = f"""Com base EXCLUSIVAMENTE no texto fornecido, elabore {num_questoes} questões da banca Quadrix inéditas com foco no assunto: "{assunto}". {regras}"""
        conteudo = [prompt, texto_base]
        
    try:
        schema = types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "enunciado": types.Schema(type=types.Type.STRING),
                    "alternativas": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
                    "resposta_correta": types.Schema(type=types.Type.STRING),
                    "explicacoes_opcoes": types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "A": types.Schema(type=types.Type.STRING), "B": types.Schema(type=types.Type.STRING),
                            "C": types.Schema(type=types.Type.STRING), "D": types.Schema(type=types.Type.STRING),
                            "E": types.Schema(type=types.Type.STRING),
                        }
                    )
                },
                required=["enunciado", "alternativas", "resposta_correta", "explicacoes_opcoes"]
            )
        )
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=conteudo,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema),
        )
        raw_text = response.text.strip()
        if raw_text.startswith("```json"): raw_text = raw_text[7:]
        if raw_text.startswith("```"): raw_text = raw_text[3:]
        if raw_text.endswith("```"): raw_text = raw_text[:-3]
        clean_text = re.sub(r',\s*([\]}])', r'\1', raw_text.strip())
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"Erro na API: {e}")
        return None

# -- ESTADO GLOBAL --
if 'logged_in_user' not in st.session_state:
    st.session_state.logged_in_user = None
    st.session_state.logged_in_username = None

if 'current_page' not in st.session_state: st.session_state.current_page = "Dashboard"
if 'view_category' not in st.session_state: st.session_state.view_category = None
if 'quiz_assunto' not in st.session_state: st.session_state.quiz_assunto = None
if 'answered' not in st.session_state: st.session_state.answered = False
if 'selected_option' not in st.session_state: st.session_state.selected_option = None
if 'questao_atual' not in st.session_state: st.session_state.questao_atual = None

load_css()

# -- TELA DE LOGIN --
if not st.session_state.logged_in_user:
    if "uid" in st.query_params and "user" in st.query_params:
        st.session_state.logged_in_user = int(st.query_params["uid"])
        st.session_state.logged_in_username = st.query_params["user"]
        st.rerun()

    st.markdown('<div class="login-box">', unsafe_allow_html=True)
    st.markdown("<h2 style='text-align: center; color: #2563eb;'>📚 SEDES DF - Login</h2>", unsafe_allow_html=True)
    login_input = st.text_input("Usuário")
    senha_input = st.text_input("Senha", type="password")
    
    if st.button("Entrar no Sistema", use_container_width=True):
        user = login_user(login_input.lower().strip(), senha_input.strip())
        if user:
            st.session_state.logged_in_user = user[0]
            st.session_state.logged_in_username = user[1].capitalize()
            st.query_params["uid"] = str(user[0])
            st.query_params["user"] = user[1].capitalize()
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# -- SIDEBAR NAVEGAÇÃO --
with st.sidebar:
    st.markdown(f"### 👋 Olá, {st.session_state.logged_in_username}")
    if st.button("🚪 Sair (Logout)", use_container_width=True):
        st.session_state.logged_in_user = None
        st.session_state.logged_in_username = None
        st.query_params.clear()
        st.rerun()
        
    st.markdown("---")
    st.markdown("### ⚙️ Cotas de API (Energia)")
    opcao_chave = st.selectbox("Qual cota usar agora?", ["Cota 1 (Principal)", "Cota 2 (Secundária)", "Cota 3 (Reserva)", "Outra (Manual)"])
    
    if opcao_chave == "Cota 1 (Principal)":
        api_key = st.secrets["GEMINI_KEY_1"]
        st.caption("🟢 Limite da Conta 1 ativado.")
    elif opcao_chave == "Cota 2 (Secundária)":
        api_key = st.secrets["GEMINI_KEY_2"]
        st.caption("🟢 Limite da Conta 2 ativado.")
    elif opcao_chave == "Cota 3 (Reserva)":
        api_key = st.secrets["GEMINI_KEY_3"]
        st.caption("🟢 Limite da Conta 3 ativado.")
    else:
        api_key = st.text_input("Cole a nova Chave API", type="password")
    
    st.markdown("---")
    st.markdown("### 🧭 Navegação")
    if st.button("📊 Meu Painel", use_container_width=True):
        st.session_state.current_page = "Dashboard"
        st.session_state.view_category = None
        st.rerun()
    if st.button("✨ Alimentar Banco (Gerar)", use_container_width=True):
        st.session_state.current_page = "Gerar"
        st.rerun()
    if st.button("✏️ Revisar Questões", use_container_width=True):
        st.session_state.current_page = "Revisar"
        st.rerun()

# -- PÁGINA: DASHBOARD --
if st.session_state.current_page == "Dashboard":
    if st.session_state.view_category is None:
        st.markdown(f"""
        <div class="app-header">
            <h1>🏛️ Pilares de Estudo - Painel do {st.session_state.logged_in_username}</h1>
            <p>Escolha a área que deseja treinar agora</p>
        </div>
        """, unsafe_allow_html=True)
        
        categorias = get_categorias()
        cols = st.columns(3)
        for i, cat in enumerate(categorias):
            with cols[i % 3]:
                st.markdown(f"<h3>{cat['nome']}</h3>", unsafe_allow_html=True)
                if st.button("Acessar Assuntos ➡️", key=f"cat_{cat['id']}"):
                    st.session_state.view_category = cat
                    st.rerun()
    else:
        cat = st.session_state.view_category
        st.markdown(f"""
        <div class="app-header">
            <h1>📊 {cat['nome']}</h1>
            <p>Seus acertos e progresso pessoal</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("⬅️ Voltar aos Pilares"):
            st.session_state.view_category = None
            st.rerun()
            
        stats = get_dashboard_stats(cat['id'], st.session_state.logged_in_user)
        stats_com_questoes = [s for s in stats if s['total'] > 0]
        
        if not stats_com_questoes:
            st.info("O Banco de Questões está vazio para esta área. Alguém precisa ir em 'Alimentar Banco' para gerar novas!")
        else:
            cols = st.columns(3)
            for i, s in enumerate(stats_com_questoes):
                with cols[i % 3]:
                    st.markdown(render_svg_chart(s["nome"], s["total"], s["respondidas"], s["acertos"]), unsafe_allow_html=True)
                    
                    if s["respondidas"] < s["total"]:
                        if st.button("Continuar Estudando ➡️", key=f"btn_{s['id']}", use_container_width=True):
                            st.session_state.current_page = "Quiz"
                            st.session_state.quiz_assunto = s['id']
                            st.session_state.questao_atual = get_proxima_questao(s['id'], st.session_state.logged_in_user)
                            st.session_state.answered = False
                            st.session_state.selected_option = None
                            st.rerun()
                    else:
                        st.button("Todas Respondidas ✅", key=f"btn_{s['id']}", disabled=True, use_container_width=True)
                        
                    if s["respondidas"] > 0:
                        if st.button("🔄 Refazer Questões", key=f"reset_{s['id']}", use_container_width=True):
                            resetar_progresso_assunto(s['id'], st.session_state.logged_in_user)
                            st.rerun()

# -- PÁGINA: QUIZ --
elif st.session_state.current_page == "Quiz":
    assunto_nome = get_nome_assunto(st.session_state.quiz_assunto)
    st.markdown(f"""
    <div class="app-header">
        <h1>📝 Área de Estudos ({st.session_state.logged_in_username})</h1>
        <p>Matéria: <b>{assunto_nome}</b></p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("⬅️ Voltar ao Painel"):
        st.session_state.current_page = "Dashboard"
        st.rerun()
        
    q = st.session_state.questao_atual
    if not q:
        st.success("🎉 Você já respondeu todas as questões desse assunto! Volte ao painel e gere mais questões se desejar.")
        if st.button("🔄 Refazer as questões desta matéria!"):
            resetar_progresso_assunto(st.session_state.quiz_assunto, st.session_state.logged_in_user)
            st.session_state.questao_atual = get_proxima_questao(st.session_state.quiz_assunto, st.session_state.logged_in_user)
            st.rerun()
    else:
        st.markdown(f'<div class="question-card">', unsafe_allow_html=True)
        st.markdown(f'<div class="question-text">{q["enunciado"]}</div>', unsafe_allow_html=True)
        
        if not st.session_state.answered:
            letra_resposta = st.radio("Selecione uma alternativa:", q["alternativas"], key=f"radio_quiz")
            if st.button("✅ Confirmar Resposta"):
                st.session_state.selected_option = letra_resposta[0]
                correta = (letra_resposta[0] == q["resposta_correta"].upper())
                salvar_resposta(q["id"], letra_resposta[0], correta, st.session_state.logged_in_user)
                st.session_state.answered = True
                st.rerun()
        else:
            selecionada = st.session_state.selected_option
            correta = q["resposta_correta"].upper()
            if selecionada == correta: st.success("🎉 Muito bem! Você acertou.")
            else: st.error(f"❌ Que pena, você errou. O gabarito correto é a letra {correta}.")
            
            explicacoes = q.get("explicacoes_opcoes", {})
            for alt in q["alternativas"]:
                letra = alt[0]
                css_class = "alt-correct" if letra == correta else ("alt-incorrect" if letra == selecionada else "alt-neutral")
                explicacao_texto = explicacoes.get(letra, "Sem explicação detalhada.")
                st.markdown(f"""
                <div class="alt-container {css_class}">
                    <div class="alt-text">{alt}</div>
                    <div class="alt-explanation">{explicacao_texto}</div>
                </div>
                """, unsafe_allow_html=True)
            
            if st.button("Próxima Questão ➡️"):
                st.session_state.questao_atual = get_proxima_questao(st.session_state.quiz_assunto, st.session_state.logged_in_user)
                st.session_state.answered = False
                st.session_state.selected_option = None
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

# -- PÁGINA: GERAR --
elif st.session_state.current_page == "Gerar":
    st.markdown("""
    <div class="app-header">
        <h1>✨ Alimentar Banco de Questões</h1>
        <p>Gere perguntas inteligentes que ficarão disponíveis para você e para a Gabi</p>
    </div>
    """, unsafe_allow_html=True)
    
    categorias = get_categorias()
    cat_nomes = [c["nome"] for c in categorias]
    cat_selecionada_nome = st.selectbox("1. Escolha a Área (Pilar):", cat_nomes)
    
    cat_id = next(c["id"] for c in categorias if c["nome"] == cat_selecionada_nome)
    assuntos = get_assuntos(cat_id)
    ass_nomes = [a["nome"] for a in assuntos]
    ass_selecionado_nome = st.selectbox("2. Escolha o Assunto do Sumário:", ass_nomes)
    
    assunto_obj = next(a for a in assuntos if a["nome"] == ass_selecionado_nome)
    
    st.markdown("---")
    st.markdown("### 🔧 Configuração da Geração")
    
    if assunto_obj["pdf"]:
        st.success(f"📌 Extração Inteligente (Smart PDF Search)\\nO sistema vai extrair cirurgicamente as páginas **{assunto_obj['start']} até {assunto_obj['end']}** do arquivo local.")
        modo_sem_pdf = False
    else:
        st.info("🌐 Conhecimento Global da IA\\nEste assunto não possui PDF vinculado. A IA usará seu conhecimento nativo (Internet) para gerar as questões de legislação/pedagogia, gastando quase zero tokens.")
        modo_sem_pdf = True
        
    num_questoes = st.slider("3. Número de questões para gerar (máx 20):", 1, 20, 10)
    
    if st.button("💾 Gerar e Compartilhar no Banco", use_container_width=True):
        with st.spinner(f"Processando e gerando questões exclusivas de {assunto_obj['nome']}..."):
            texto_contexto = ""
            if not modo_sem_pdf:
                texto_contexto = extrair_texto_smart(assunto_obj["pdf"], assunto_obj["start"], assunto_obj["end"])
            
            novas = gerar_questoes_ia(api_key, texto_contexto, assunto_obj["nome"], num_questoes, modo_sem_pdf)
            
            if novas:
                salvar_questoes_db(assunto_obj["id"], novas)
                st.success(f"✅ {len(novas)} questões geradas com sucesso! Elas agora estão salvas no banco local.")
                if st.button("Ir para o Dashboard"):
                    st.session_state.current_page = "Dashboard"
                    st.rerun()

# -- PÁGINA: REVISAR QUESTÕES --
elif st.session_state.current_page == "Revisar":
    st.markdown("""
    <div class="app-header">
        <h1>✏️ Revisão do Banco de Questões</h1>
        <p>Edite enunciados, corrija gabaritos ou remova questões ruins</p>
    </div>
    """, unsafe_allow_html=True)
    
    categorias = get_categorias()
    cat_nomes = [c["nome"] for c in categorias]
    cat_selecionada_nome = st.selectbox("1. Escolha a Área (Pilar):", cat_nomes, key="rev_cat")
    
    cat_id = next(c["id"] for c in categorias if c["nome"] == cat_selecionada_nome)
    assuntos = get_assuntos(cat_id)
    ass_nomes = [a["nome"] for a in assuntos]
    ass_selecionado_nome = st.selectbox("2. Escolha o Assunto:", ass_nomes, key="rev_ass")
    assunto_id = next(a["id"] for a in assuntos if a["nome"] == ass_selecionado_nome)
    
    st.markdown("---")
    todas = get_todas_questoes(assunto_id)
    if not todas:
        st.info("Nenhuma questão encontrada para este assunto.")
    else:
        st.write(f"**Total de questões:** {len(todas)}")
        for idx, q in enumerate(todas):
            with st.expander(f"Questão {idx+1}: {q['enunciado'][:60]}..."):
                with st.form(key=f"form_q_{q['id']}"):
                    novo_enunciado = st.text_area("Enunciado", q["enunciado"], height=100)
                    
                    st.write("Alternativas:")
                    letras = ["A", "B", "C", "D", "E"]
                    novas_alts = []
                    for i in range(5):
                        alt_atual = q["alternativas"][i] if i < len(q["alternativas"]) else ""
                        if alt_atual.startswith(letras[i] + ")"):
                            alt_atual = alt_atual[3:].strip()
                        elif alt_atual.startswith(letras[i] + " -"):
                            alt_atual = alt_atual[4:].strip()
                        elif alt_atual.startswith(letras[i] + "."):
                            alt_atual = alt_atual[3:].strip()
                            
                        novo_txt = st.text_input(f"Letra {letras[i]}", alt_atual)
                        novas_alts.append(f"{letras[i]}) {novo_txt}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        correta_atual = q["resposta_correta"].upper().strip()
                        if correta_atual not in letras: correta_atual = "A"
                        nova_correta = st.selectbox("Gabarito Correto:", letras, index=letras.index(correta_atual))
                    
                    with col2:
                        explicacoes = q.get("explicacoes_opcoes", {})
                        if isinstance(explicacoes, dict):
                            exp_texto = explicacoes.get(nova_correta, "")
                        else:
                            exp_texto = str(explicacoes)
                        nova_exp = st.text_area("Explicação (opcional)", exp_texto, height=70)
                    
                    col_save, col_del = st.columns([1, 1])
                    with col_save:
                        if st.form_submit_button("💾 Salvar Alterações", use_container_width=True):
                            novas_exp_dict = {}
                            for l in letras:
                                novas_exp_dict[l] = nova_exp if l == nova_correta else "Incorreta."
                            atualizar_questao(q["id"], novo_enunciado, novas_alts, nova_correta, novas_exp_dict)
                            st.success("Atualizada com sucesso!")
                            st.rerun()
                            
                    with col_del:
                        if st.form_submit_button("🗑️ Deletar Questão", use_container_width=True):
                            deletar_questao(q["id"])
                            st.warning("Questão apagada!")
                            st.rerun()
