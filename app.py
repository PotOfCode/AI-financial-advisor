from flask import Flask, render_template, request, session, redirect, url_for
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from flask import jsonify
from flask import flash  # Añade esto al inicio
#from google.generativeai import GenerativeModel
import requests
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')
from flask import Flask, session, request
import os
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
from pyDolarVenezuela.pages import BCV
from pyDolarVenezuela import Monitor
import pytz


app = Flask(__name__)
# Añade esta ruta antes de las demás
def obtener_tasas_bcv():
    try:
        # Configurar zona horaria
        zone = pytz.timezone('America/Caracas')
        
        # Obtener datos del dólar BCV
        monitor_dolar = Monitor(BCV, 'USD')
        dolar_data = monitor_dolar.get_value_monitors("usd")
        
        # Obtener datos del euro BCV
        monitor_euro = Monitor(BCV, 'EUR')
        euro_data = monitor_euro.get_value_monitors("eur")
        
        # Formatear última actualización
        last_update_dt = dolar_data.last_update.astimezone(zone)
        formatted_last_update = last_update_dt.strftime('%d/%m/%Y, %I:%M %p')
        
        return {
            'bcv_dolar': dolar_data.price,
            'bcv_euro': euro_data.price,
            'last_update': formatted_last_update,
            'error': False
        }
    except Exception as e:
        print(f"Error obteniendo tasas BCV: {e}")
        # Valores por defecto en caso de error
        return {
            'bcv_dolar': 92.83,
            'bcv_euro': 100.64,
            'last_update': datetime.now().strftime('%d/%m/%Y, %I:%M %p'),
            'error': True
        }

# Ruta API para obtener tasas (actualizada)
@app.route('/api/tasas')
def obtener_tasas():
    tasas = obtener_tasas_bcv()
    return jsonify(tasas)

#app.secret_key = os.environ.get('SECRET_KEY')
app.secret_key = 'IL4LbtIP4r'

CORS(app)  # Permite solicitudes desde cualquier origen

GOOGLE_API_KEY = os.environ.get(
    'GEMINI_API_KEY', 'AIzaSyDwd3D2AFDF9MLzSSx7SPuHG9KVZcuQ6-M')  # Para desarrollo
genai.configure(api_key=GOOGLE_API_KEY)


# Inicialización segura del modelo

def get_chat_session():
    if 'chat' not in session:
        model = genai.GenerativeModel('gemini-2.0-flash')
        session['chat'] = model.start_chat(history=[]).history
    return genai.GenerativeModel('gemini-2.0-flash').start_chat(history=session['chat'])

@app.before_request
def inicializar_datos():
    if 'datos' not in session:
        session['datos'] = {
            'ingresos': 0,
            'gastos': {'Comida': 0, 'Transporte': 0, 'Vivienda': 0, 'Otros': 0},
            'deudas': 0,
            'ahorros': 0
        }
    # Actualizar tasas en cada solicitud
    session['tasas'] = obtener_tasas_bcv()

@app.route('/')
def index():
    return redirect(url_for('registro'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        try:
            session['datos'] = {
                'ingresos': max(0, float(request.form['ingresos'])),
                'gastos': {
                    'Comida': max(0, float(request.form['comida'])),
                    'Transporte': max(0, float(request.form['transporte'])),
                    'Vivienda': max(0, float(request.form['vivienda'])),
                    'Otros': max(0, float(request.form['otros']))
                },
                'deudas': max(0, float(request.form['deudas'])),
                'ahorros': max(0, float(request.form['ahorros']))
            }
            session.modified = True
        except ValueError:
            flash('Error: Ingresa solo valores numéricos válidos')
        return redirect(url_for('registro'))
    
    return render_template('registro.html', datos=session['datos'])

@app.route('/asistente')
def asistente():
    return render_template('asistente.html')

@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(error):
    return jsonify({
        "status": "error",
        "message": "Recurso no encontrado" if error.code == 404 else "Error interno del servidor"
    }), error.code

@app.route('/api/chat', methods=['POST'])
def chat_handler():
    try:
        data = request.get_json()
        user_message = data.get('message', '')

         # Manejar solicitudes de tasas de cambio
        if any(keyword in user_message for keyword in ['dólar', 'dolar', 'euro', 'tasa', 'bcv', 'bolívares']):
            tasas = session.get('tasas', obtener_tasas_bcv())
            response_text = (
                f"💰 Tasas de cambio oficiales BCV (actualizadas el {tasas['last_update']}):\n"
                f"- Dólar: {tasas['bcv_dolar']} Bs/USD\n"
                f"- Euro: {tasas['bcv_euro']} Bs/EUR"
            )
            return jsonify({
                "response": response_text,
                "status": "success"
            })
            
        # Validar entrada
        if not user_message:
            return jsonify({"status": "error", "message": "Mensaje vacío"}), 400
            
        # Lógica de Gemini
        chat = get_chat_session()
        response = chat.send_message(
            f"Responde como experto financiero, pero puedes responder datos generales a los que puedes tener acceso desde la red de forma fácil como la hora o la fecha del día, usando EXCLUSIVAMENTE texto plano sin formato. "
            f"Prohibido usar: Markdown, HTML, listas con viñetas, encabezados o símbolos especiales. "
            f"Evita cualquier formato especial, listas con viñetas o encabezados. "
            f"Pregunta: {user_message}"
        )
        
        return jsonify({
            "response": response.text,
            "status": "success"
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "Error al procesar la solicitud"
        }), 500

@app.route('/analizador')
def analizador():
    gastos = session['datos']['gastos']
    
    # Filtrar categorías con valores mayores a 0
    valores = []
    etiquetas = []
    for categoria, monto in gastos.items():
        if monto > 0:
            valores.append(monto)
            etiquetas.append(categoria)
    
    # Verificar si hay datos para graficar
    if sum(valores) == 0 or len(valores) == 0:
        plot_url = None
    else:
        # Generar gráfico de pastel
        img = BytesIO()
        plt.figure(figsize=(8, 8))
        plt.pie(valores, 
                labels=etiquetas,
                autopct='%1.1f%%',
                startangle=140)
        plt.title('Distribución de Gastos')
        plt.axis('equal')
        plt.savefig(img, format='png')
        plt.close()
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
    
    # Regla 50/30/20 con validación
    try:
        ingresos = float(session['datos']['ingresos'])
    except (KeyError, ValueError):
        ingresos = 0
        
    presupuesto = {
        'necesidades': ingresos * 0.5 if ingresos > 0 else 0,
        'deseos': ingresos * 0.3 if ingresos > 0 else 0,
        'ahorro': ingresos * 0.2 if ingresos > 0 else 0
    }

    return render_template('analizador.html', 
                         plot_url=plot_url,
                         presupuesto=presupuesto)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    app.run(debug=True)
