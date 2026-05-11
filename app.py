# filepath: app.py
from flask import Flask, jsonify, request, render_template, url_for
from flask_cors import CORS
import json
import os
import uuid
from supabase import create_client, Client

app = Flask(__name__)
CORS(app, origins=[
    "https://provao.onrender.com",
    "https://provao-1.onrender.com",
    "https://lightskyblue-grouse-667245.hostingersite.com",
    "null"
])

# ── Carregamento do JSON para sugestões ──────────────────────────────────────
JSON_FILE_PATH = 'output_multi_sheet.json'

def load_json_data():
    try:
        with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        app.logger.warning(f"Arquivo JSON {JSON_FILE_PATH} não encontrado.")
        return {}
    except Exception as e:
        app.logger.error(f"Erro ao carregar {JSON_FILE_PATH}: {e}")
        return {}

json_data_for_suggestions = load_json_data()

# ── Sugestões de autocomplete ────────────────────────────────────────────────
SUGGESTIONS_JSON_PATH = 'suggestions_data.json'
suggestions_data = {}
try:
    with open(SUGGESTIONS_JSON_PATH, 'r', encoding='utf-8') as f:
        suggestions_data = json.load(f)
    app.logger.info(f"Sugestões carregadas com sucesso.")
except Exception as e:
    app.logger.warning(f"Erro ao carregar sugestões: {e}")

# ── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "https://iradczvlimgyukwbwqcl.supabase.co")
SUPABASE_KEY: str = os.environ.get("SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlyYWRjenZsaW1"
    "neXVrd2J3cWNsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDgxMTQwMDcsImV4cCI6MjA2MzY5MDAwN30"
    ".CcLvcjhUaNvgSEHFunka_Er-RQ8iwMKInP5lvIrlqIY")
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Páginas ───────────────────────────────────────────────────────────────────
@app.route('/')
def index_page():
    return render_template('index.html')

@app.route('/formulario')
def formulario_page():
    return render_template('formulario.html')

@app.route('/links')
def links_page():
    return render_template('links.html')

@app.route('/visualizador_pdf')
def visualizador_pdf_page():
    return render_template('visualizador_pdf.html')

# ── Rotas de sugestões (JSON local) ──────────────────────────────────────────
@app.route('/get_json_categories')
def get_json_categories():
    return jsonify(list(json_data_for_suggestions.keys()))

@app.route('/get_json_institutions')
def get_json_institutions():
    category = request.args.get('category')
    if not category or category not in json_data_for_suggestions:
        return jsonify([]), 400
    category_data = json_data_for_suggestions[category]
    institutions = sorted(list(set(
        item.get('Instituição', '') for item in category_data if item.get('Instituição')
    )))
    return jsonify(institutions)

@app.route('/get_json_courses')
def get_json_courses():
    category = request.args.get('category')
    if not category or category not in json_data_for_suggestions:
        return jsonify([]), 400
    category_data = json_data_for_suggestions[category]
    courses = sorted(list(set(
        item.get('Curso', '') for item in category_data if item.get('Curso')
    )))
    return jsonify(courses)

@app.route('/get_all_institutions')
def get_all_institutions():
    return jsonify(suggestions_data.get('institutions', []))

@app.route('/get_all_courses')
def get_all_courses():
    return jsonify(suggestions_data.get('courses', []))

# ── Nova rota: valores únicos disponíveis para os filtros ────────────────────
@app.route('/get_filter_options')
def get_filter_options():
    """
    Retorna os valores únicos disponíveis no banco para popular
    os selects de Ano, Semestre e Chamada dinamicamente.
    """
    try:
        resp_anos = (
            supabase_client.table("dados_formulario")
            .select("ano_resultado")
            .not_.is_("ano_resultado", "null")
            .execute()
        )
        anos = sorted(list(set(
            r["ano_resultado"] for r in resp_anos.data if r.get("ano_resultado")
        )), reverse=True)

        resp_sems = (
            supabase_client.table("dados_formulario")
            .select("semestre")
            .not_.is_("semestre", "null")
            .execute()
        )
        semestres_ordem = ["1º semestre", "2º semestre"]
        semestres_brutos = set(r["semestre"] for r in resp_sems.data if r.get("semestre"))
        semestres = [s for s in semestres_ordem if s in semestres_brutos]

        resp_chs = (
            supabase_client.table("dados_formulario")
            .select("chamada")
            .not_.is_("chamada", "null")
            .execute()
        )
        chamadas_ordem = [
            "1ª chamada", "2ª chamada", "3ª chamada",
            "1ª lista de espera", "2ª lista de espera", "3ª lista de espera",
        ]
        chamadas_brutos = set(r["chamada"] for r in resp_chs.data if r.get("chamada"))
        chamadas = [c for c in chamadas_ordem if c in chamadas_brutos]

        return jsonify({
            "anos": anos,
            "semestres": semestres,
            "chamadas": chamadas,
        })
    except Exception as e:
        app.logger.error(f"Erro em /get_filter_options: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ── Rota principal de busca no Supabase (atualizada) ─────────────────────────
@app.route('/search_supabase', methods=['POST'])
def search_supabase():
    try:
        data = request.get_json()
        app.logger.info(f"Payload recebido em /search_supabase: {data}")

        selected_category    = data.get('category')
        selected_institution = data.get('institution')
        selected_course      = data.get('course')
        # ── novos filtros ──
        selected_ano         = data.get('ano_resultado')   # int ou None
        selected_semestre    = data.get('semestre')        # "1º semestre" | "2º semestre" | None
        selected_chamada     = data.get('chamada')         # "1ª chamada" | … | None

        if not selected_category:
            return jsonify({"error": "Categoria (tipo_cota) é obrigatória."}), 400

        query = (
            supabase_client.table("dados_formulario")
            .select("instituicao, curso, numero_unico, tipo_cota, semestre, chamada, ano_resultado", count='exact')
        )

        # ── Filtros existentes ──
        query = query.ilike("tipo_cota", f"{selected_category}%")

        if selected_course:
            query = query.ilike("curso", f"%{selected_course.strip()}%")

        if selected_institution:
            query = query.ilike("instituicao", f"%{selected_institution.strip()}%")

        # ── Filtros novos ──
        if selected_ano:
            try:
                query = query.eq("ano_resultado", int(selected_ano))
            except (ValueError, TypeError):
                pass

        if selected_semestre:
            query = query.eq("semestre", selected_semestre)

        if selected_chamada:
            query = query.eq("chamada", selected_chamada)

        query = query.order("numero_unico", desc=True)

        response = query.execute()
        app.logger.info(f"Supabase: count={response.count}")

        if hasattr(response, 'data'):
            return jsonify(response.data)
        else:
            return jsonify({"error": "Erro ao buscar dados no Supabase"}), 500

    except Exception as e:
        app.logger.error(f"Exceção em /search_supabase: {e}", exc_info=True)
        return jsonify({"error": "Erro interno do servidor", "details": str(e)}), 500



# ── Redações — Supabase Service Key (para escrita privilegiada) ───────────────
SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

def get_service_client():
    """Cliente com service_role para operações privilegiadas (monitores)."""
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    return create_client(SUPABASE_URL, key)

# ── ROTA: Página do visualizador de redações ──────────────────────────────────
@app.route('/redacoes')
def redacoes_page():
    return render_template('redacoes.html')

# ── ROTA: Listar redações públicas (galeria) ──────────────────────────────────
@app.route('/redacao/listar', methods=['GET'])
def redacao_listar():
    try:
        vestibular = request.args.get('vestibular')   # 'enem'|'fuvest'|'provao'
        ano        = request.args.get('ano')
        destaque   = request.args.get('destaque')     # '1' para só destaques

        query = (
            supabase_client.table('redacoes')
            .select('id, vestibular, ano, tema, nota_total, nota_c1, nota_c2, '
                    'nota_c3, nota_c4, nota_c5, status, destaque, drive_url, '
                    'arquivo_url, feedback_geral, pontos_fortes, pontos_melhoria, '
                    'monitor_nome, corrigida_em, arquivo_nome')
            .eq('publica', True)
            .order('destaque', desc=True)
            .order('nota_total', desc=True)
        )

        if vestibular:
            query = query.eq('vestibular', vestibular)
        if ano:
            try:    query = query.eq('ano', int(ano))
            except: pass
        if destaque == '1':
            query = query.eq('destaque', True)

        resp = query.limit(50).execute()
        return jsonify(resp.data or [])

    except Exception as e:
        app.logger.error(f"Erro em /redacao/listar: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ── ROTA: Enviar redação (candidato) ─────────────────────────────────────────
@app.route('/redacao/enviar', methods=['POST'])
def redacao_enviar():
    try:
        # Suporte a JSON (drive_url) e multipart (upload de PDF)
        if request.is_json:
            data = request.get_json()
            tipo_envio  = 'drive'
            drive_url   = data.get('drive_url', '').strip()
            arquivo_url  = None
            arquivo_nome = None
            if not drive_url:
                return jsonify({'error': 'Link do Drive é obrigatório.'}), 400
            # Validação básica do link
            if 'drive.google.com' not in drive_url:
                return jsonify({'error': 'Informe um link válido do Google Drive.'}), 400
        else:
            # Upload de PDF
            tipo_envio = 'upload'
            drive_url  = None
            arquivo    = request.files.get('arquivo')
            data       = request.form

            if not arquivo:
                return jsonify({'error': 'Nenhum arquivo enviado.'}), 400
            if not arquivo.filename.lower().endswith('.pdf'):
                return jsonify({'error': 'Somente arquivos PDF são aceitos.'}), 400
            if arquivo.content_length and arquivo.content_length > 10 * 1024 * 1024:
                return jsonify({'error': 'Arquivo muito grande (máximo 10 MB).'}), 400

            # Upload para Supabase Storage
            arquivo_bytes = arquivo.read()
            arquivo_nome  = arquivo.filename
            storage_path  = f"redacoes/{uuid.uuid4()}.pdf"

            try:
                supabase_client.storage.from_('redacoes').upload(
                    path=storage_path,
                    file=arquivo_bytes,
                    file_options={'content-type': 'application/pdf'}
                )
                arquivo_url = supabase_client.storage.from_('redacoes').get_public_url(storage_path)
            except Exception as e:
                app.logger.error(f"Erro no upload Storage: {e}")
                return jsonify({'error': 'Erro ao fazer upload do arquivo. Tente novamente.'}), 500

        # Montar registro
        def parse_nota(val):
            try:    return float(str(val).replace(',', '.'))
            except: return None

        nota_c1 = parse_nota(data.get('nota_c1'))
        nota_c2 = parse_nota(data.get('nota_c2'))
        nota_c3 = parse_nota(data.get('nota_c3'))
        nota_c4 = parse_nota(data.get('nota_c4'))
        nota_c5 = parse_nota(data.get('nota_c5'))

        notas = [nota_c1, nota_c2, nota_c3, nota_c4, nota_c5]
        nota_total = round(sum(n for n in notas if n is not None), 2) if any(
            n is not None for n in notas
        ) else None

        registro = {
            'nome_candidato':  data.get('nome_candidato') or None,
            'email_candidato': data.get('email_candidato') or None,
            'contato_extra':   data.get('contato_extra') or None,
            'vestibular':      data.get('vestibular', 'enem'),
            'ano':             int(data.get('ano')) if data.get('ano') else None,
            'tema':            data.get('tema') or None,
            'tipo_envio':      tipo_envio,
            'arquivo_url':     arquivo_url if tipo_envio == 'upload' else None,
            'drive_url':       drive_url,
            'arquivo_nome':    arquivo_nome if tipo_envio == 'upload' else None,
            'nota_c1':         nota_c1,
            'nota_c2':         nota_c2,
            'nota_c3':         nota_c3,
            'nota_c4':         nota_c4,
            'nota_c5':         nota_c5,
            'nota_total':      nota_total,
            'status':          'pendente',
            'publica':         False,
        }

        resp = supabase_client.table('redacoes').insert(registro).execute()
        app.logger.info(f"Redação enviada: {resp.data}")
        return jsonify({'success': True, 'id': resp.data[0]['id'] if resp.data else None})

    except Exception as e:
        app.logger.error(f"Erro em /redacao/enviar: {e}", exc_info=True)
        return jsonify({'error': 'Erro interno ao enviar redação.', 'details': str(e)}), 500

# ── ROTA: Listar para monitores (todas, não só públicas) ─────────────────────
@app.route('/redacao/monitor/listar', methods=['POST'])
def redacao_monitor_listar():
    try:
        body  = request.get_json()
        senha = body.get('senha', '')
        MONITOR_SENHA = os.environ.get('MONITOR_SENHA', 'meuprovao2025')
        if senha != MONITOR_SENHA:
            return jsonify({'error': 'Senha incorreta.'}), 403

        status_filtro = body.get('status')  # opcional

        query = (
            get_service_client().table('redacoes')
            .select('*')
            .order('criado_em', desc=True)
        )
        if status_filtro:
            query = query.eq('status', status_filtro)

        resp = query.limit(100).execute()
        return jsonify(resp.data or [])

    except Exception as e:
        app.logger.error(f"Erro em /redacao/monitor/listar: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ── ROTA: Salvar correção do monitor ─────────────────────────────────────────
@app.route('/redacao/corrigir', methods=['POST'])
def redacao_corrigir():
    try:
        body  = request.get_json()
        senha = body.get('senha', '')
        MONITOR_SENHA = os.environ.get('MONITOR_SENHA', 'meuprovao2025')
        if senha != MONITOR_SENHA:
            return jsonify({'error': 'Senha incorreta.'}), 403

        redacao_id = body.get('id')
        if not redacao_id:
            return jsonify({'error': 'ID da redação é obrigatório.'}), 400

        def parse_nota(val):
            try:    return float(str(val).replace(',', '.'))
            except: return None

        nota_c1 = parse_nota(body.get('nota_c1'))
        nota_c2 = parse_nota(body.get('nota_c2'))
        nota_c3 = parse_nota(body.get('nota_c3'))
        nota_c4 = parse_nota(body.get('nota_c4'))
        nota_c5 = parse_nota(body.get('nota_c5'))
        notas   = [nota_c1, nota_c2, nota_c3, nota_c4, nota_c5]
        nota_total = round(sum(n for n in notas if n is not None), 2) if any(
            n is not None for n in notas
        ) else None

        novo_status = body.get('status', 'corrigida')
        publica = body.get('publica', False)
        destaque = body.get('destaque', False)

        update_data = {
            'status':          novo_status,
            'monitor_nome':    body.get('monitor_nome'),
            'feedback_geral':  body.get('feedback_geral'),
            'feedback_c1':     body.get('feedback_c1'),
            'feedback_c2':     body.get('feedback_c2'),
            'feedback_c3':     body.get('feedback_c3'),
            'feedback_c4':     body.get('feedback_c4'),
            'feedback_c5':     body.get('feedback_c5'),
            'pontos_fortes':   body.get('pontos_fortes'),
            'pontos_melhoria': body.get('pontos_melhoria'),
            'nota_c1':         nota_c1,
            'nota_c2':         nota_c2,
            'nota_c3':         nota_c3,
            'nota_c4':         nota_c4,
            'nota_c5':         nota_c5,
            'nota_total':      nota_total,
            'nota_confirmada': True,
            'publica':         publica,
            'destaque':        destaque,
            'corrigida_em':    'now()',
        }
        # Remover chaves None para não sobrescrever dados existentes
        update_data = {k: v for k, v in update_data.items() if v is not None}

        resp = get_service_client().table('redacoes').update(update_data).eq('id', redacao_id).execute()
        return jsonify({'success': True, 'data': resp.data})

    except Exception as e:
        app.logger.error(f"Erro em /redacao/corrigir: {e}", exc_info=True)
        return jsonify({'error': 'Erro ao salvar correção.', 'details': str(e)}), 500

# ── ROTA: Publicar redações existentes (seed manual) ─────────────────────────
@app.route('/redacao/publicar_seed', methods=['POST'])
def redacao_publicar_seed():
    """
    Rota para inserir redações do banco local (PDFs seus) via payload JSON.
    Use uma única vez para popular a galeria inicial.
    Requer senha de monitor.
    """
    try:
        body  = request.get_json()
        senha = body.get('senha', '')
        MONITOR_SENHA = os.environ.get('MONITOR_SENHA', 'meuprovao2025')
        if senha != MONITOR_SENHA:
            return jsonify({'error': 'Senha incorreta.'}), 403

        redacoes = body.get('redacoes', [])
        if not redacoes:
            return jsonify({'error': 'Nenhuma redação enviada.'}), 400

        inseridas = []
        for r in redacoes:
            registro = {
                'vestibular':     r.get('vestibular', 'enem'),
                'ano':            r.get('ano'),
                'tema':           r.get('tema'),
                'tipo_envio':     r.get('tipo_envio', 'drive'),
                'drive_url':      r.get('drive_url'),
                'arquivo_url':    r.get('arquivo_url'),
                'nota_c1':        r.get('nota_c1'),
                'nota_c2':        r.get('nota_c2'),
                'nota_c3':        r.get('nota_c3'),
                'nota_c4':        r.get('nota_c4'),
                'nota_c5':        r.get('nota_c5'),
                'nota_total':     r.get('nota_total'),
                'status':         r.get('status', 'destacada'),
                'publica':        r.get('publica', True),
                'destaque':       r.get('destaque', False),
                'monitor_nome':   r.get('monitor_nome'),
                'feedback_geral': r.get('feedback_geral'),
                'pontos_fortes':  r.get('pontos_fortes'),
                'tema':           r.get('tema'),
            }
            resp = get_service_client().table('redacoes').insert(registro).execute()
            if resp.data:
                inseridas.append(resp.data[0]['id'])

        return jsonify({'success': True, 'inseridas': len(inseridas), 'ids': inseridas})

    except Exception as e:
        app.logger.error(f"Erro em /redacao/publicar_seed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ── Novas páginas — Frente 3 ─────────────────────────────────────────────────
@app.route('/sobre')
def sobre_page():
    return render_template('sobre.html')

@app.route('/vestibulares')
def vestibulares_page():
    return render_template('vestibulares.html')

@app.route('/blog')
def blog_page():
    return render_template('blog.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=True, host='0.0.0.0', port=port)
