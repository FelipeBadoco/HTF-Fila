import sys
import os
import time

# Adiciona o diretório atual ao path para garantir importação correta
sys.path.append(os.getcwd())

try:
    from monitor_service import MonitorService
except ImportError as e:
    print(f"Erro de importação: {e}")
    sys.exit(1)

def test_monitor():
    print(">>> Iniciando teste do MonitorService...")
    
    try:
        service = MonitorService()
    except Exception as e:
        print(f"xxx Erro ao instanciar MonitorService: {e}")
        return

    print("\n1. Buscando dados (primeira vez - sem cache)...")
    start = time.time()
    try:
        data1 = service.get_dashboard_data()
    except Exception as e:
        print(f"xxx Erro ao buscar dados: {e}")
        return
    duration = time.time() - start
    print(f"   v Dados obtidos em {duration:.4f}s")
    
    if 'dados' in data1:
         print(f"   v Encontrados {len(data1['dados'])} trabalhos.")
    else:
         print("   x Estrutura de dados incorreta.")

    print("\n2. Buscando dados (segunda vez - DEVE usar cache)...")
    start = time.time()
    data2 = service.get_dashboard_data()
    duration = time.time() - start
    print(f"   v Dados obtidos em {duration:.4f}s")
    
    if data1['last_update'] == data2['last_update']:
        print("   >>> SUCESSO: Cache funcionou (timestamps idênticos).")
    else:
        print("   >>> AVISO: Timestamps diferentes. Cache não funcionou como esperado.")
        print(f"T1: {data1['last_update']}")
        print(f"T2: {data2['last_update']}")

if __name__ == "__main__":
    test_monitor()
