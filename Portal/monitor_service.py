import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import psutil
from config import INSTANCES_DIRECTORY, MONITORED_SERVICE_NAME, CACHE_TTL

class MonitorService:
    def __init__(self):
        self._cache_data = None
        self._last_update = None
    
    def get_dashboard_data(self):
        """
        Retorna os dados do dashboard, usando cache se disponível e recente.
        """
        now = datetime.now()
        
        # Verifica Cache
        if (self._cache_data and self._last_update and 
            (now - self._last_update).total_seconds() < CACHE_TTL):
            return self._cache_data

        # Se cache expirou ou não existe, busca dados novos
        dados_tmp, mensagem = self._ler_arquivos_tmp(INSTANCES_DIRECTORY)
        status_servico = self._verificar_status_servico(MONITORED_SERVICE_NAME)
        
        mensagem_servico = None
        if status_servico == 'stopped':
            mensagem_servico = f"Atenção: O serviço '{MONITORED_SERVICE_NAME}' está parado. O sistema pode não funcionar corretamente."
        elif status_servico == 'not_found':
            mensagem_servico = f"Erro: O serviço '{MONITORED_SERVICE_NAME}' não foi encontrado nesta máquina."

        # Cálculos de estatísticas
        total_trabalhos = len(dados_tmp)
        # Proteção contra valores inválidos em Pages
        total_paginas = 0
        for item in dados_tmp:
            try:
                total_paginas += int(item.get('Pages', 0))
            except (ValueError, TypeError):
                pass
                
        processando = sum(1 for item in dados_tmp if 'process' in item.get('State', '').lower())

        # Monta o objeto de dados
        self._cache_data = {
            'dados': dados_tmp,
            'mensagem': mensagem,
            'mensagem_servico': mensagem_servico,
            'status_servico': status_servico,
            'total_trabalhos': total_trabalhos,
            'total_paginas': total_paginas,
            'processando': processando,
            'last_update': now.strftime('%d-%m-%Y %H:%M:%S')
        }
        self._last_update = now
        
        return self._cache_data

    def _ler_arquivos_tmp(self, diretorio):
        """
        Lê e processa todos os arquivos .tmp no diretório.
        """
        dados = []
        if not os.path.isdir(diretorio):
            return [], "Erro: O diretório de instâncias não foi encontrado ou está inacessível."

        try:
            for root_dir, _, files in os.walk(diretorio):
                for filename in files:
                    if filename.lower().endswith(".tmp"):
                        caminho = os.path.join(root_dir, filename)
                        xml_info = self._parse_xml_file(caminho)
                        if xml_info:
                            dados.append(xml_info)
        except Exception as e:
            return [], f"Erro ao acessar diretório de rede: {str(e)}"

        if not dados:
            return [], "Não há trabalhos em processamento."

        # Ordenação: mais antigos primeiro (processamento em ordem segura)
        # Usamos uma chave segura para evitar erros de comparação
        def sort_key(x):
            try:
                return datetime.strptime(x.get('Time', ''), '%d-%m-%Y %H:%M:%S')
            except (ValueError, TypeError):
                return datetime.min

        dados.sort(key=sort_key)

        return dados, None

    def _parse_xml_file(self, caminho):
        """Tenta fazer parse de um arquivo XML único com tratamento de erro robusto."""
        try:
            tree = ET.parse(caminho)
            root = tree.getroot()

            xml_info = {}
            xml_info['Name'] = root.findtext('Name', 'N/A')
            xml_info['State'] = root.findtext('State', 'N/A')
            xml_info['Pages'] = root.findtext('Pages', '0')
            xml_info['User'] = root.findtext('User', 'N/A')
            xml_info['Site'] = root.findtext('Site', 'N/A')

            # Porcentagem
            percentage_text = root.findtext('Percentage', '0').strip().replace('%', '')
            try:
                xml_info['Percentage'] = int(float(percentage_text))
            except (ValueError, TypeError):
                xml_info['Percentage'] = 0

            # Tempo
            time_text = root.findtext('Time', '').strip()
            # Tenta converter para formato padrão de exibição
            try:
                # O formato original parece ser YYYY-MM-DD HH:MM:SS.f
                if '.' in time_text:
                     dt_obj = datetime.strptime(time_text, '%Y-%m-%d %H:%M:%S.%f')
                else:
                     dt_obj = datetime.strptime(time_text, '%Y-%m-%d %H:%M:%S')
                xml_info['Time'] = dt_obj.strftime('%d-%m-%Y %H:%M:%S')
            except ValueError:
                xml_info['Time'] = time_text

            return xml_info
        except (ET.ParseError, OSError, IOError):
            return None

    def _verificar_status_servico(self, servico_nome):
        """Verifica o status do serviço."""
        try:
            servico = psutil.win_service_get(servico_nome)
            return servico.status()
        except psutil.NoSuchProcess:
            return "not_found"
        except Exception:
            # Caso genérico para evitar crash se psutil falhar
            return "unknown"
