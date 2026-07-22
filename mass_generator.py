import os
import fitz
import json
import psycopg2
from google import genai
from google.genai import types
import time
import sys
import random
import concurrent.futures

# Pega as chaves
SUPABASE_URL = "postgresql://postgres.jhlmayeaeqlxowzmnnsv:%4019216801GgJlsp2000%23@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"
GEMINI_KEYS = [
    os.environ.get("GEMINI_KEY_1", ""),
    os.environ.get("GEMINI_KEY_2", ""),
    os.environ.get("GEMINI_KEY_3", ""),
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

sys.path.append(r"C:\Users\vitor\OneDrive\Área de Trabalho\App_Sedes_Cloud")
from seed_data import ESTRUTURA_ASSUNTOS

def extrair_texto_pdf(caminho, start, end):
    if not caminho or not os.path.exists(caminho):
        return ""
    try:
        doc = fitz.open(caminho)
        texto = ""
        # 0-indexed pages
        for i in range(start - 1, min(end, len(doc))):
            texto += doc[i].get_text() + "\n"
        return texto
    except Exception as e:
        print(f"Erro ao ler PDF {caminho}: {e}")
        return ""

def calcular_num_questoes_alvo(assunto, area):
    """Calcula quantas questões totais o assunto merece com base na densidade."""
    pages = 0
    if assunto.get("pdf") and assunto.get("end") and assunto.get("start"):
        pages = assunto["end"] - assunto["start"] + 1
        
    if "Pedagogia" in area or "Administração" in area:
        base = 6
    elif "Língua Portuguesa" in area or "Distrito Federal" in area:
        base = 8
    else:
        base = 4
        
    if pages > 30:
        base += 6
    elif pages > 15:
        base += 4
        
    return min(12, max(4, base))

def gerar_questoes_ia(client, texto_base, assunto, num_questoes, enunciados_existentes=None):
    regras = f"""
    REGRAS CRÍTICAS DE GERAÇÃO (PADRÃO BANCA QUADRIX):
    1. Você é o examinador sênior da banca QUADRIX elaborando uma prova oficial para a SEDES-DF.
    2. Crie {num_questoes} questões inéditas e de alto nível de dificuldade sobre o assunto: "{assunto}".
    3. As questões podem pedir a alternativa CORRETA ou a INCORRETA (exceção). A Quadrix usa muitas pegadinhas semânticas.
    4. IMPORTANTE: O campo 'resposta_correta' no JSON deve OBRIGATORIAMENTE conter apenas a letra (A, B, C, D ou E) do gabarito definitivo.
    5. Cada questão deve ter exatamente 5 alternativas (A, B, C, D, E).
    6. As questões devem ser TOTALMENTE INÉDITAS, diferentes de quaisquer outras que você já tenha gerado sobre este assunto.
    """

    if enunciados_existentes:
        lista_enunciados = "\n".join([f"- {e}" for e in enunciados_existentes])
        regras += f"\n    7. ATENÇÃO MÁXIMA ANTI-DUPLICAÇÃO: As seguintes questões já existem no banco para este assunto. VOCÊ ESTÁ PROIBIDO de criar questões com foco idêntico, estrutura igual ou perguntando exatamente a mesma coisa que os seguintes enunciados:\n{lista_enunciados}\n"

    if texto_base:
        prompt = f"""Com base no material de estudo fornecido abaixo, {regras}
        
        [MATERIAL DE ESTUDO]
        {texto_base[:25000]}
        """
    else:
        prompt = f"""Use seus vastos conhecimentos atualizados sobre concursos públicos, leis e pedagogia social para elaborar as questões. {regras}"""

    try:
        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "enunciado": {"type": "STRING"},
                    "alternativas": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    },
                    "resposta_correta": {"type": "STRING"},
                    "explicacoes_opcoes": {
                        "type": "OBJECT",
                        "properties": {
                            "A": {"type": "STRING"},
                            "B": {"type": "STRING"},
                            "C": {"type": "STRING"},
                            "D": {"type": "STRING"},
                            "E": {"type": "STRING"}
                        }
                    }
                },
                "required": ["enunciado", "alternativas", "resposta_correta", "explicacoes_opcoes"]
            }
        }

        def _call_api():
            return client.models.generate_content(
                model='gemini-3.5-flash-lite',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.8
                ),
            )
            
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_call_api)
        response = future.result(timeout=45)
        executor.shutdown(wait=False, cancel_futures=True)
            
        return json.loads(response.text)
    except Exception as e:
        print(f"Erro na IA para o assunto {assunto}: {e}")
        return []

def processar_assunto(conn, c, client, assunto, nome_assunto, area, assunto_id, num_questoes_alvo):
    texto_pdf = ""
    if assunto.get("pdf"):
        texto_pdf = extrair_texto_pdf(assunto["pdf"], assunto["start"], assunto["end"])
    
    # Busca os enunciados já existentes no banco para evitar duplicatas
    c.execute("SELECT enunciado FROM questoes WHERE assunto_id = %s;", (assunto_id,))
    enunciados_existentes = [row[0] for row in c.fetchall()]

    # Divide em lotes de no máximo 4 questões por vez para evitar timeout/429
    lotes = []
    restante = num_questoes_alvo
    while restante > 0:
        lote_atual = min(4, restante)
        lotes.append(lote_atual)
        restante -= lote_atual
        
    global key_idx
    total_inserido = 0
    
    for lote in lotes:
        tentativas = 0
        sucesso = False
        while tentativas < 10 and not sucesso:
            questoes = gerar_questoes_ia(client, texto_pdf, nome_assunto, lote, enunciados_existentes)
            
            if questoes and isinstance(questoes, list) and len(questoes) > 0:
                for q in questoes:
                    try:
                        c.execute("""
                            INSERT INTO questoes (assunto_id, enunciado, alternativas, resposta_correta, explicacoes)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            assunto_id,
                            q.get("enunciado", ""),
                            json.dumps(q.get("alternativas", [])),
                            q.get("resposta_correta", "A"),
                            json.dumps(q.get("explicacoes_opcoes", {}))
                        ))
                        total_inserido += 1
                    except Exception as e:
                        print(f"Erro ao inserir questão: {e}")
                conn.commit()
                print(f"    ✅ +{len(questoes)} questões inseridas (Lote).")
                sucesso = True
            else:
                tentativas += 1
                print(f"    ❌ Falha. Tentativa {tentativas}/10. Trocando chave API e aguardando 61s...")
                key_idx = (key_idx + 1) % len(GEMINI_KEYS)
                client = genai.Client(api_key=GEMINI_KEYS[key_idx])
                time.sleep(61)
                
        time.sleep(2)
    return total_inserido, client

def executar_fase(fase, conn, c, assuntos_db, assuntos_ja_gerados, client):
    total_sucesso = 0
    for area, assuntos in ESTRUTURA_ASSUNTOS.items():
        print(f"\n🚀 Iniciando Área: {area}")
        
        for assunto in assuntos:
            nome_assunto = assunto["nome"]
            if nome_assunto not in assuntos_db:
                print(f"⚠️ Assunto não encontrado no DB, pulando: {nome_assunto}")
                continue
                
            assunto_id = assuntos_db[nome_assunto]
            
            if fase == 1:
                # Na fase 1, só roda se NÃO tiver sido gerado ainda
                if assunto_id in assuntos_ja_gerados:
                    continue
                num_alvo = 3 # Apenas 3 questões para os últimos pendentes difíceis para garantir que passa
                print(f"  [FASE 1] ⏳ Resgatando pendente: {nome_assunto[:50]}...")
                
            elif fase == 2:
                # Na fase 2, roda para todos calculando a densidade
                num_alvo = calcular_num_questoes_alvo(assunto, area)
                c.execute("SELECT count(*) FROM questoes WHERE assunto_id = %s;", (assunto_id,))
                qtd_atual = c.fetchone()[0]
            elif fase == 3:
                # Na fase 3, gerar exatamente 4 questões NOVAS para cada assunto
                # ignorando quantas já existem
                num_alvo = 4
                print(f"  [FASE 3] ⏳ Aprofundamento Anti-Duplicatas (+4q): {nome_assunto[:50]}...")
                
            inseridas, client = processar_assunto(conn, c, client, assunto, nome_assunto, area, assunto_id, num_alvo)
            total_sucesso += inseridas
            
    return total_sucesso, client

key_idx = 0

def main():
    global key_idx
    conn = psycopg2.connect(SUPABASE_URL)
    c = conn.cursor()
    c.execute("SELECT id, nome FROM assuntos;")
    assuntos_db = {nome: id for id, nome in c.fetchall()}
    
    c.execute("SELECT assunto_id FROM questoes GROUP BY assunto_id HAVING count(*) > 0;")
    assuntos_ja_gerados = {row[0] for row in c.fetchall()}
    
    client = genai.Client(api_key=GEMINI_KEYS[key_idx])
    
    print("\n--- INICIANDO FASE 3: AMPLIAÇÃO ANTI-DUPLICATAS (+4 QUESTÕES POR ASSUNTO) ---")
    sucesso_fase3, client = executar_fase(3, conn, c, assuntos_db, assuntos_ja_gerados, client)
    print(f"\n✅ FASE 3 CONCLUÍDA! {sucesso_fase3} novas questões geradas.")
    
    conn.close()
    print(f"\n🎉 SCRIPT TOTALMENTE FINALIZADO! Foram geradas {sucesso_fase3} novas questões nesta sessão!")

if __name__ == "__main__":
    main()
