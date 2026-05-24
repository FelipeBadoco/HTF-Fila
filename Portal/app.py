from flask import Flask, render_template, make_response, jsonify
from waitress import serve
from monitor_service import MonitorService

app = Flask(__name__)

# Instancia o serviço de monitoramento
# Ele gerencia o estado e o cache internamente
monitor_service = MonitorService()

@app.route('/')
def index():
    """Rota que renderiza a página HTML inicial."""
    response = make_response(render_template('index.html'))
    # Headers para evitar cache do navegador na página principal
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/data')
def api_data():
    """Endpoint da API que fornece os dados em formato JSON."""
    # Obtém dados do serviço (já com cache configurado)
    data = monitor_service.get_dashboard_data()
    return jsonify(data)

if __name__ == "__main__":
    print("Servidor iniciado em http://0.0.0.0:5000")
    serve(app, host='0.0.0.0', port=5000)