import re
import psycopg2

DB_URL = "postgresql://postgres.jhlmayeaeqlxowzmnnsv:%4019216801GgJlsp2000%23@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"

def clean_enunciado(texto):
    """
    Remove any pre-existing numbering like '1.', 'Questão 1 -', 'Questão 42:', etc.
    """
    # Regex para pegar formatos como "Questão X - ", "1. ", "Questão X:", "12)", etc no INÍCIO da string.
    pattern = re.compile(r'^(?:Quest[aã]o\s*\d+\s*[\-\:]?\s*|\d+[\.\-\)]\s*)', re.IGNORECASE)
    
    cleaned = texto.strip()
    # Roda enquanto o padrão bater, para limpar coisas como "Questão 1 - 1. "
    while pattern.match(cleaned):
        cleaned = pattern.sub('', cleaned).strip()
        
    return cleaned

def run():
    print("Conectando ao banco de dados...")
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    
    print("Buscando lista de assuntos...")
    cursor.execute("SELECT DISTINCT assunto_id FROM questoes;")
    assuntos = [row[0] for row in cursor.fetchall()]
    
    total_atualizadas = 0
    
    for assunto_id in assuntos:
        # Busca todas as questões deste assunto na ordem em que foram criadas
        cursor.execute("SELECT id, enunciado FROM questoes WHERE assunto_id = %s ORDER BY id ASC;", (assunto_id,))
        questoes = cursor.fetchall()
        
        print(f"Processando assunto_id {assunto_id} ({len(questoes)} questões)...")
        
        for i, (q_id, enunciado) in enumerate(questoes, start=1):
            cleaned = clean_enunciado(enunciado)
            
            # Aplica a nova numeração padronizada
            novo_enunciado = f"Questão {i} - {cleaned}"
            
            cursor.execute("UPDATE questoes SET enunciado = %s WHERE id = %s;", (novo_enunciado, q_id))
            total_atualizadas += 1
            
        # Salva as alterações para cada assunto
        conn.commit()
        
    print(f"\\nFinalizado com sucesso! {total_atualizadas} questões foram renumeradas e padronizadas.")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    run()
