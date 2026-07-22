from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import json
import psycopg2
import os
import re

DB_URL = os.environ.get("SUPABASE_URL", "postgresql://postgres.jhlmayeaeqlxowzmnnsv:%4019216801GgJlsp2000%23@aws-1-sa-east-1.pooler.supabase.com:5432/postgres")

def get_db():
    return psycopg2.connect(DB_URL)

def clean_json_res(data):
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            return data
    return data

class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        
        # Serve static assets if Vercel routes css/js/manifest to function
        if parsed.path.startswith('/css/') or parsed.path.startswith('/js/') or parsed.path == '/manifest.json':
            try:
                rel_path = parsed.path.lstrip('/')
                mime = 'text/css' if rel_path.endswith('.css') else ('application/javascript' if rel_path.endswith('.js') else 'application/json')
                self.send_response(200)
                self.send_header('Content-Type', f'{mime}; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                with open(rel_path, 'rb') as f:
                    self.wfile.write(f.read())
                return
            except Exception:
                pass

        params = parse_qs(parsed.query)
        action = params.get('action', [''])[0]

        # If no action is specified (root page request), serve index.html
        if not action or action == 'html':
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                with open('index.html', 'rb') as f:
                    self.wfile.write(f.read())
                return
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=500)
                return

        try:
            conn = get_db()
            cursor = conn.cursor()

            if action == 'login':
                login = params.get('login', [''])[0].lower().strip()
                senha = params.get('senha', [''])[0].strip()
                cursor.execute("SELECT id, login FROM usuarios WHERE login = %s AND senha = %s", (login, senha))
                row = cursor.fetchone()
                cursor.close()
                conn.close()
                if row:
                    self._send_json({"success": True, "user_id": row[0], "username": row[1].capitalize()})
                else:
                    self._send_json({"success": False, "error": "Usuário ou senha incorretos."}, status=401)
                return

            elif action == 'categorias':
                cursor.execute("SELECT id, nome FROM categorias ORDER BY id ASC")
                res = [{"id": r[0], "nome": r[1]} for r in cursor.fetchall()]
                cursor.close()
                conn.close()
                self._send_json({"success": True, "categorias": res})
                return

            elif action == 'dashboard':
                cat_id = int(params.get('categoria_id', [0])[0])
                usuario_id = int(params.get('usuario_id', [0])[0])
                query = '''
                    SELECT a.id, a.nome,
                           COUNT(DISTINCT q.id) as total_questoes,
                           COUNT(DISTINCT r.questao_id) as total_respondidas,
                           SUM(CASE WHEN r.correta = TRUE THEN 1 ELSE 0 END) as total_acertos
                    FROM assuntos a
                    LEFT JOIN questoes q ON a.id = q.assunto_id
                    LEFT JOIN respostas r ON q.id = r.questao_id AND r.usuario_id = %s
                    WHERE a.categoria_id = %s
                    GROUP BY a.id, a.nome
                    ORDER BY a.id ASC
                '''
                cursor.execute(query, (usuario_id, cat_id))
                stats = []
                for row in cursor.fetchall():
                    if row[2] > 0: # Apenas assuntos com questões
                        stats.append({
                            "id": row[0],
                            "nome": row[1],
                            "total": row[2],
                            "respondidas": row[3],
                            "acertos": row[4] if row[4] else 0
                        })
                cursor.close()
                conn.close()
                self._send_json({"success": True, "assuntos": stats})
                return

            elif action == 'questoes':
                assunto_id = int(params.get('assunto_id', [0])[0])
                usuario_id = int(params.get('usuario_id', [0])[0])

                # Nome do assunto
                cursor.execute("SELECT nome FROM assuntos WHERE id = %s", (assunto_id,))
                ass_row = cursor.fetchone()
                assunto_nome = ass_row[0] if ass_row else "Assunto"

                # Busca todas as questões
                cursor.execute("""
                    SELECT id, enunciado, alternativas, resposta_correta, explicacoes
                    FROM questoes
                    WHERE assunto_id = %s
                    ORDER BY id ASC
                """, (assunto_id,))
                rows = cursor.fetchall()

                # Busca respostas do usuario
                cursor.execute("SELECT questao_id, resposta_dada, correta FROM respostas WHERE usuario_id = %s", (usuario_id,))
                respostas_map = {r[0]: {"resposta_dada": r[1], "correta": r[2]} for r in cursor.fetchall()}

                cursor.close()
                conn.close()

                questoes_list = []
                letras = ["A", "B", "C", "D", "E"]

                for r in rows:
                    q_id = r[0]
                    enunciado = r[1]
                    alts_brutas = clean_json_res(r[2])
                    correta_db = r[3].strip().upper()[0] if r[3] else "A"
                    explicacoes = clean_json_res(r[4])

                    alts_formatadas = []
                    for i, alt in enumerate(alts_brutas):
                        if i < len(letras):
                            if alt.startswith(letras[i] + ")") or alt.startswith(letras[i] + " -") or alt.startswith(letras[i] + "."):
                                alts_formatadas.append(alt)
                            else:
                                alts_formatadas.append(f"{letras[i]}) {alt}")
                        else:
                            alts_formatadas.append(alt)

                    user_resp = respostas_map.get(q_id, None)

                    questoes_list.append({
                        "id": q_id,
                        "enunciado": enunciado,
                        "alternativas": alts_formatadas,
                        "resposta_correta": correta_db,
                        "explicacoes": explicacoes,
                        "resposta_usuario": user_resp
                    })

                self._send_json({"success": True, "assunto_nome": assunto_nome, "questoes": questoes_list})
                return

            else:
                cursor.close()
                conn.close()
                self._send_json({"success": False, "error": "Ação inválida."}, status=400)
                return

        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body.decode('utf-8'))
            action = data.get('action', '')

            conn = get_db()
            cursor = conn.cursor()

            if action == 'responder':
                questao_id = int(data.get('questao_id'))
                resposta_dada = data.get('resposta').strip().upper()[0]
                usuario_id = int(data.get('usuario_id'))

                # Pega resposta correta da questão
                cursor.execute("SELECT resposta_correta FROM questoes WHERE id = %s", (questao_id,))
                correta_raw = cursor.fetchone()[0]
                correta_letra = correta_raw.strip().upper()[0] if correta_raw else "A"
                is_correct = (resposta_dada == correta_letra)

                # Insere ou atualiza resposta
                cursor.execute("DELETE FROM respostas WHERE questao_id = %s AND usuario_id = %s", (questao_id, usuario_id))
                cursor.execute("INSERT INTO respostas (questao_id, resposta_dada, correta, usuario_id) VALUES (%s, %s, %s, %s)",
                               (questao_id, resposta_dada, is_correct, usuario_id))
                conn.commit()
                cursor.close()
                conn.close()

                self._send_json({"success": True, "correta": is_correct, "resposta_correta": correta_letra})
                return

            elif action == 'reset':
                assunto_id = int(data.get('assunto_id'))
                usuario_id = int(data.get('usuario_id'))

                cursor.execute("""
                    DELETE FROM respostas 
                    WHERE usuario_id = %s 
                    AND questao_id IN (SELECT id FROM questoes WHERE assunto_id = %s)
                """, (usuario_id, assunto_id))
                conn.commit()
                cursor.close()
                conn.close()

                self._send_json({"success": True, "message": "Progresso reiniciado."})
                return

            else:
                cursor.close()
                conn.close()
                self._send_json({"success": False, "error": "Ação inválida."}, status=400)
                return

        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)
