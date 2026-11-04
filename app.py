from flask import Flask, render_template, make_response, jsonify, request, session
import paramiko
import os
import xml.etree.ElementTree as ET
from datetime import datetime
import time
import threading
from waitress import serve
import psutil
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()

# --- Configurações da Aplicação ---
# Agora as configurações são lidas do arquivo .env
DIRETORIO_INSTANCIAS = os.getenv('DIRETORIO_INSTANCIAS', r'\\150.230.74.141\volumes\htfapps-volume\_data\instances')
NOME_SERVICO_MONITORADO = os.getenv('NOME_SERVICO_MONITORADO', "WFDesignerBIService")
PORTA_APP = int(os.getenv('FLASK_PORT', 5000))
DIRETORIO_LOGS = os.getenv('DIRETORIO_LOGS', r'\\10.18.4.90\volumes\htfapps-volume\_data\logs')
VERSAO_APP = os.getenv('VERSAO_APP', '2.4')

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'htf_portal_admin_secret_key_2026')

# --- Cache de Dados ---
# Armazena os dados processados dos arquivos .tmp para evitar re-parsing desnecessário
# Estrutura: { 'caminho_arquivo': { 'mtime': 12345, 'dados': {xml_info} } }
CACHE_DADOS = {}

# --- Dados Compartilhados (Cache de Memória) ---
# Armazena o estado atual compilado para entrega instantânea nas rotas de API
DADOS_COMPARTILHADOS = {
    'dados': [],
    'mensagem': "Carregando dados, por favor aguarde...",
    'mensagem_servico': None,
    'status_servico': 'unknown',
    'total_trabalhos': 0,
    'total_paginas': 0,
    'processando': 0,
    'last_update': 'Nunca',
    'versao': VERSAO_APP
}

def ler_arquivos_tmp(diretorio):
    """
    Lê e processa todos os arquivos .tmp em um diretório e seus subdiretórios.
    Usa cache baseado no tempo de modificação (mtime) para alta performance.
    """
    global CACHE_DADOS
    dados_atualizados = []
    arquivos_encontrados = set()

    if not os.path.isdir(diretorio):
        return [], "Erro: O diretório de instâncias não foi encontrado ou está inacessível."

    for root_dir, _, files in os.walk(diretorio):
        for filename in files:
            if filename.endswith(".tmp"):
                caminho = os.path.join(root_dir, filename)
                arquivos_encontrados.add(caminho)
                
                try:
                    mtime = os.path.getmtime(caminho)
                    
                    # Se o arquivo já estiver no cache e não foi modificado, usa o cache
                    if caminho in CACHE_DADOS and CACHE_DADOS[caminho]['mtime'] == mtime:
                        dado = dict(CACHE_DADOS[caminho]['dados'])
                        if 'Hash' not in dado:
                            dado['Hash'] = os.path.splitext(os.path.basename(caminho))[0]
                        dados_atualizados.append(dado)
                        continue

                    # Caso contrário, processa o arquivo XML
                    tree = ET.parse(caminho)
                    root = tree.getroot()

                    tag_hash = (root.findtext('Hash') or root.findtext('Id') or root.findtext('InstanceId') or '').strip()
                    hash_arquivo = tag_hash if tag_hash else os.path.splitext(filename)[0]

                    xml_info = {
                        'Hash': hash_arquivo,
                        'Name': root.findtext('Name', 'N/A'),
						'State': 'Aguardando' if root.findtext('State', 'N/A') == 'Digitalizando' else root.findtext('State', 'N/A'),
                        'Pages': root.findtext('Pages', '0'),
                        'User': root.findtext('User', 'N/A'),
                        'Site': root.findtext('Site', 'N/A')
                    }

                    # Tratamento robusto para Porcentagem
                    percentage_text = root.findtext('Percentage', '0').strip().replace('%', '')
                    try:
                        xml_info['Percentage'] = int(float(percentage_text))
                    except (ValueError, TypeError):
                        xml_info['Percentage'] = 0

                    # Tratamento robusto para Tempo
                    time_text = root.findtext('Time', '').strip()
                    dt_obj = None
                    try:
                        dt_obj = datetime.strptime(time_text, '%Y-%m-%d %H:%M:%S.%f')
                        xml_info['Time'] = dt_obj.strftime('%d-%m-%Y %H:%M:%S')
                    except ValueError:
                        xml_info['Time'] = time_text

                    # Guarda o datetime objeto para ordenação segura sem quebrar caso de formato inválido
                    if dt_obj:
                        xml_info['_sort_time'] = dt_obj
                    else:
                        try:
                            xml_info['_sort_time'] = datetime.strptime(xml_info['Time'], '%d-%m-%Y %H:%M:%S')
                        except ValueError:
                            xml_info['_sort_time'] = datetime.min

                    # Atualiza o cache
                    CACHE_DADOS[caminho] = {'mtime': mtime, 'dados': xml_info}
                    dados_atualizados.append(dict(xml_info))

                except (ET.ParseError, OSError) as e:
                    print(f"Aviso: Erro ao processar {caminho}: {e}")
                    continue

    # Limpeza de Cache: remove arquivos que não existem mais fisicamente
    caminhos_no_cache = list(CACHE_DADOS.keys())
    for caminho in caminhos_no_cache:
        if caminho not in arquivos_encontrados:
            del CACHE_DADOS[caminho]

    if not dados_atualizados:
        return [], "Não há trabalhos em processamento."

    # Ordena os dados por data/hora (do mais antigo para o mais novo) de forma segura
    dados_atualizados.sort(key=lambda x: x.get('_sort_time', datetime.min), reverse=False)

    # Limpa o campo temporário antes de retornar
    for item in dados_atualizados:
        item.pop('_sort_time', None)

    return dados_atualizados, None

def verificar_status_servico(servico_nome):
    """Verifica o status de um serviço do Windows (com fallback multiplataforma)."""
    if not hasattr(psutil, 'win_service_get'):
        return "not_implemented"
    try:
        servico = psutil.win_service_get(servico_nome)
        return servico.status()  # ex: 'running', 'stopped'
    except psutil.NoSuchProcess:
        return "not_found" # Retorna um estado claro se o serviço não existe

def thread_atualizacao_dados():
    """Thread que realiza a varredura e cálculos em background, evitando travar requisições HTTP."""
    global DADOS_COMPARTILHADOS
    intervalo = int(os.getenv('INTERVALO_VARREDURA', 3))
    print(f"[Thread Background] Iniciada. Intervalo de varredura: {intervalo} segundos.")
    
    while True:
        try:
            dados_tmp, mensagem = ler_arquivos_tmp(DIRETORIO_INSTANCIAS)
            status_servico = verificar_status_servico(NOME_SERVICO_MONITORADO)
            mensagem_servico = None
            
            if status_servico == 'stopped':
                mensagem_servico = f"Atenção: O serviço '{NOME_SERVICO_MONITORADO}' está parado. O sistema pode não funcionar corretamente."
            elif status_servico == 'not_found':
                mensagem_servico = f"Erro: O serviço '{NOME_SERVICO_MONITORADO}' não foi encontrado nesta máquina."
            elif status_servico == 'not_implemented':
                # Mensagem amigável para plataformas que não suportam serviços Windows
                mensagem_servico = f"Aviso: Monitoramento do serviço Windows '{NOME_SERVICO_MONITORADO}' não disponível nesta plataforma."

            # Cálculos
            total_trabalhos = len(dados_tmp)
            total_paginas = sum(int(item.get('Pages', 0)) for item in dados_tmp)
            processando = sum(1 for item in dados_tmp if item.get('State') != 'Aguardando')

            # Atualiza de forma atômica o cache
            DADOS_COMPARTILHADOS = {
                'dados': dados_tmp,
                'mensagem': mensagem,
                'mensagem_servico': mensagem_servico,
                'status_servico': status_servico,
                'total_trabalhos': total_trabalhos,
                'total_paginas': total_paginas,
                'processando': processando,
                'last_update': datetime.now().strftime('%d-%m-%Y %H:%M:%S'),
                'versao': VERSAO_APP
            }
        except Exception as e:
            print(f"[Thread Background] Erro durante varredura: {e}")
            
        time.sleep(intervalo)

def get_dashboard_data():
    """
    Função central que retorna os dados pré-coletados em cache.
    """
    return DADOS_COMPARTILHADOS

@app.route('/')
def index():
    """Rota que renderiza a página HTML inicial."""
    # Apenas renderiza o template. Os dados serão carregados via API.
    # Isso melhora a percepção de velocidade para o usuário.
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/logs')
def logs():
    """Rota que renderiza a página HTML de logs em tela cheia."""
    response = make_response(render_template('logs.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/data')
def api_data():
    """Endpoint da API que fornece os dados em formato JSON."""
    # Chama a função centralizada para obter os dados
    data = get_dashboard_data()
    # Usa jsonify para retornar a resposta JSON formatada corretamente
    return jsonify(data)

@app.route('/api/logs')
def api_logs():
    """Retorna a lista de arquivos de log e o conteúdo do log selecionado (ou o mais recente)."""
    import glob
    
    if not os.path.isdir(DIRETORIO_LOGS):
        return jsonify({
            'erro': f"Diretório de logs não encontrado ou inacessível: {DIRETORIO_LOGS}",
            'arquivos': [],
            'linhas': []
        })
    
    # Lista arquivos .log no diretório
    arquivos_log = glob.glob(os.path.join(DIRETORIO_LOGS, "*.log"))
    
    if not arquivos_log:
        return jsonify({
            'erro': "Nenhum arquivo de log (.log) encontrado.",
            'arquivos': [],
            'linhas': []
        })
        
    # Ordena por mtime para identificar os mais recentes
    arquivos_ordenados = sorted(
        [{'nome': os.path.basename(p), 'caminho': p, 'mtime': os.path.getmtime(p)} for p in arquivos_log],
        key=lambda x: x['mtime'],
        reverse=True
    )
    
    # Pega o arquivo solicitado ou o mais recente
    arquivo_solicitado = request.args.get('file')
    caminho_selecionado = None
    nome_selecionado = None
    
    if arquivo_solicitado:
        # Prevenção contra Path Traversal
        arquivo_solicitado = os.path.basename(arquivo_solicitado)
        caminho_candidato = os.path.join(DIRETORIO_LOGS, arquivo_solicitado)
        if os.path.exists(caminho_candidato):
            caminho_selecionado = caminho_candidato
            nome_selecionado = arquivo_solicitado
            
    if not caminho_selecionado:
        caminho_selecionado = arquivos_ordenados[0]['caminho']
        nome_selecionado = arquivos_ordenados[0]['nome']
        
    # Lê as últimas N linhas usando tail eficiente
    limit = request.args.get('limit', 150, type=int)
    linhas = []
    try:
        with open(caminho_selecionado, 'rb') as f:
            f.seek(0, os.SEEK_END)
            tamanho = f.tell()
            # Lê os últimos 128KB (suficiente para mais de 150 linhas grandes)
            bloco = min(131072, tamanho)
            if bloco > 0:
                f.seek(tamanho - bloco)
                dados_bytes = f.read(bloco)
                dados_texto = dados_bytes.decode('utf-8', errors='ignore')
                linhas_todas = dados_texto.splitlines()
                # Remove primeira linha pois pode ser parcial
                if bloco < tamanho and len(linhas_todas) > 0:
                    linhas_todas.pop(0)
                linhas = linhas_todas[-limit:]
    except Exception as e:
        linhas = [f"Erro ao ler o arquivo {nome_selecionado}: {e}"]
        
    lista_nomes = [a['nome'] for a in arquivos_ordenados]
    
    # Ordenação especial para priorizar os arquivos solicitados pelo usuário no dropdown
    principais = ['alfresco.log', 'capture.log', 'captureprocessor.log','connector.log', 'licensing.log','share.log','solr.log','tools.log']
    arquivos_finais = [p for p in principais if p in lista_nomes]
    arquivos_finais += [a for a in lista_nomes if a not in arquivos_finais]
    
    return jsonify({
        'arquivo_atual': nome_selecionado,
        'arquivos': arquivos_finais,
        'linhas': linhas,
        'versao': VERSAO_APP
    })


# --- Módulo Administrativo e SSH ---
def executar_comando_ssh(comando):
    """Conecta ao servidor Linux via SSH e executa o comando com timeout seguro."""
    host = os.getenv('SSH_HOST', '10.18.4.90')
    port = int(os.getenv('SSH_PORT', 22))
    user = os.getenv('SSH_USER', 'root')
    password = os.getenv('SSH_PASSWORD', '')

    if not host or not user:
        return False, "Configurações de SSH incompletas no arquivo .env (SSH_HOST ou SSH_USER não definidos)."

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            password=password if password else None,
            timeout=10,
            banner_timeout=10
        )
        stdin, stdout, stderr = client.exec_command(comando, timeout=180)
        saida = stdout.read().decode('utf-8', errors='ignore')
        erro = stderr.read().decode('utf-8', errors='ignore')
        client.close()

        texto_final = (saida + ("\n" + erro if erro else "")).strip()
        return True, texto_final if texto_final else "Comando executado sem retorno de texto."
    except Exception as e:
        return False, f"Falha na conexão SSH ({user}@{host}:{port}): {str(e)}"

@app.route('/admin')
def admin_page():
    """Página administrativa protegida por senha."""
    if not session.get('admin_autenticado'):
        return render_template('admin_login.html')
    return render_template('admin.html',
                           ssh_host=os.getenv('SSH_HOST', '10.18.4.90'),
                           ssh_user=os.getenv('SSH_USER', 'root'),
                           contentstore_path=os.getenv('CONTENTSTORE_DELETED_PATH', '/var/lib/docker/volumes/alfresco-content-data-volume/_data/contentstore.deleted'))

@app.route('/api/admin/login', methods=['POST'])
def api_admin_login():
    """Autentica o acesso à área administrativa."""
    data = request.get_json() or {}
    senha_informada = data.get('senha', '')
    senha_correta = os.getenv('ADMIN_PASSWORD', 'admin123')

    if senha_informada == senha_correta:
        session['admin_autenticado'] = True
        return jsonify({'sucesso': True})
    return jsonify({'sucesso': False, 'erro': 'Senha incorreta.'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def api_admin_logout():
    """Encerra a sessão administrativa."""
    session.pop('admin_autenticado', None)
    return jsonify({'sucesso': True})

@app.route('/api/admin/check-contentstore', methods=['POST'])
def api_admin_check_contentstore():
    """Verifica o caminho, existência, tamanho e arquivos de contentstore.deleted sem apagar nada."""
    if not session.get('admin_autenticado'):
        return jsonify({'erro': 'Não autorizado'}), 401

    caminho = os.getenv('CONTENTSTORE_DELETED_PATH', '/var/lib/docker/volumes/alfresco-content-data-volume/_data/contentstore.deleted')

    cmd = f'''
    target="{caminho}"
    echo "========================================================"
    echo "         VERIFICAÇÃO DE CONTENTSTORE.DELETED           "
    echo "========================================================"
    echo "[DATA/HORA] $(date '+%d/%m/%Y %H:%M:%S')"
    echo "[HOSTNAME]  $(hostname)"
    echo "[USUÁRIO]   $(whoami)"
    echo "[CAMINHO]   $target"
    echo "--------------------------------------------------------"
    if [ ! -d "$target" ]; then
        echo "[STATUS] [FALHA] O diretório não existe ou o volume não está montado!"
        exit 1
    fi
    echo "[STATUS] [OK] Diretório encontrado e acessível."
    echo ""
    echo "[ANÁLISE DE CONTEÚDO]"
    TAMANHO=$(du -sh "$target" 2>/dev/null | awk '{{print $1}}')
    TOTAL_ARQS=$(find "$target" -type f 2>/dev/null | wc -l)
    TOTAL_PASTAS=$(find "$target" -mindepth 1 -type d 2>/dev/null | wc -l)
    echo "Espaço total ocupado : $TAMANHO"
    echo "Quantidade de arquivos: $TOTAL_ARQS"
    echo "Subdiretórios         : $TOTAL_PASTAS"
    echo ""
    echo "[AMOSTRA DOS 5 ITENS MAIS RECENTES/MODIFICADOS]"
    ls -lht "$target" 2>/dev/null | head -n 6
    echo "--------------------------------------------------------"
    echo "Verificação concluída. Pronto para limpeza caso confirme."
    '''

    sucesso, saida = executar_comando_ssh(cmd)
    return jsonify({
        'sucesso': sucesso,
        'caminho': caminho,
        'saida': saida
    })

@app.route('/api/admin/clean-contentstore', methods=['POST'])
def api_admin_clean_contentstore():
    """Efetua a limpeza segura do conteúdo interno da pasta contentstore.deleted."""
    if not session.get('admin_autenticado'):
        return jsonify({'erro': 'Não autorizado'}), 401

    data = request.get_json() or {}
    if not data.get('confirmar'):
        return jsonify({'erro': 'Confirmação obrigatória não recebida'}), 400

    caminho = os.getenv('CONTENTSTORE_DELETED_PATH', '/var/lib/docker/volumes/alfresco-content-data-volume/_data/contentstore.deleted')

    # Validação de segurança estrita para evitar remoção de caminhos incorretos
    if not caminho or len(caminho.strip()) < 15 or 'contentstore.deleted' not in caminho:
        return jsonify({'erro': 'Caminho inválido ou inseguro para exclusão'}), 400

    cmd = f'''
    target="{caminho}"
    echo "========================================================"
    echo "          LIMPEZA DE CONTENTSTORE.DELETED              "
    echo "========================================================"
    echo "[DATA/HORA] $(date '+%d/%m/%Y %H:%M:%S')"
    echo "[CAMINHO]   $target"
    if [ ! -d "$target" ]; then
        echo "[ERRO] Diretório não existe. Operação abortada."
        exit 1
    fi

    echo "Espaço ocupado antes da limpeza: $(du -sh "$target" 2>/dev/null | awk '{{print $1}}')"
    echo "Apagando arquivos e subpastas internas..."
    find "$target" -mindepth 1 -delete
    echo "Exclusão finalizada."
    echo ""
    echo "Espaço ocupado após a limpeza: $(du -sh "$target" 2>/dev/null | awk '{{print $1}}')"
    echo "[SUCESSO] contentstore.deleted limpo com êxito!"
    '''

    sucesso, saida = executar_comando_ssh(cmd)
    return jsonify({
        'sucesso': sucesso,
        'saida': saida
    })

if __name__ == "__main__":
    # Inicia a varredura em segundo plano
    t = threading.Thread(target=thread_atualizacao_dados, daemon=True)
    t.start()
    
    print(f"Servidor iniciado em http://0.0.0.0:{PORTA_APP}")
    serve(app, host='0.0.0.0', port=PORTA_APP)