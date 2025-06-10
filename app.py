from flask import Flask, render_template, request, session, redirect, url_for, jsonify, flash
import google.generativeai as genai
import requests # Se mantiene por si lo necesitas en otro lado, pero no es estrictamente necesario para Monitor de pyDolarVenezuela
import pandas as pd # Se mantiene si lo usas en otro lado
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg') # Usar backend no interactivo para matplotlib
import os
from flask_cors import CORS
from datetime import datetime
from pyDolarVenezuela.pages import BCV
from pyDolarVenezuela import Monitor
import pytz

app = Flask(__name__)
# Usar una clave secreta segura, especialmente en producción
# IMPORTANTE: Reemplaza 'your_default_fallback_secret_key' con una cadena aleatoria fuerte
# y preferiblemente configúrala a través de una variable de entorno en producción.
app.secret_key = 'IL4LbtIP4r' 

CORS(app) # Permitir solicitudes desde cualquier origen

# Configurar la clave de API de Gemini
# IMPORTANTE: Configúrala a través de una variable de entorno en producción
GOOGLE_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyDwd3D2AFDF9MLzSSx7SPuHG9KVZcuQ6-M') 
genai.configure(api_key=GOOGLE_API_KEY)


# --- Función auxiliar para obtener las tasas del BCV ---
# Movida hacia arriba para una mejor organización
def obtener_tasas_bcv():
    """Obtiene las tasas más recientes de dólar y euro del BCV."""
    try:
        # Configurar zona horaria
        zone = pytz.timezone('America/Caracas')
        
        # Obtener datos del dólar BCV
        monitor_dolar = Monitor(BCV, 'USD')
        # Obtener específicamente el valor de la fuente "BCV"
        dolar_data = monitor_dolar.get_value_monitors("BCV") 
        
        # Obtener datos del euro BCV
        monitor_euro = Monitor(BCV, 'EUR')
        # Obtener específicamente el valor de la fuente "BCV"
        euro_data = monitor_euro.get_value_monitors("BCV") 
        
        # Formatear hora de última actualización
        # Asegurarse de que last_update es un objeto datetime antes de formatear
        last_update_dt = dolar_data.last_update 
        if not isinstance(last_update_dt, datetime):
             # Manejar casos donde last_update podría no ser datetime (e.g., None o string)
             # Recurrir a la hora actual o un marcador de posición
             last_update_dt = datetime.now(zone) # Usar hora actual si la original no es válida
             print("Advertencia: BCV last_update no era un objeto datetime.")
        
        # Asegurarse de que last_update_dt tiene información de zona horaria antes de convertir
        if last_update_dt.tzinfo is None:
             last_update_dt = zone.localize(last_update_dt) # Asumir hora local si es "naive"

        formatted_last_update = last_update_dt.astimezone(zone).strftime('%d/%m/%Y, %I:%M %p')
        
        print(f"Tasas BCV obtenidas exitosamente. Dólar: {dolar_data.price}, Euro: {euro_data.price}") # Registrar éxito

        return {
            'bcv_dolar': dolar_data.price,
            'bcv_euro': euro_data.price,
            'last_update': formatted_last_update,
            'error': False
        }
    except Exception as e:
        print(f"Error al obtener tasas BCV: {e}") # Registrar el error
        # Valores por defecto en caso de error
        # Usar marcadores de posición que indiquen fallo o que claramente no son reales
        return {
            'bcv_dolar': "N/A", # Usar N/A o 0 para mostrar que falló
            'bcv_euro': "N/A",
            'last_update': datetime.now(pytz.timezone('America/Caracas')).strftime('%d/%m/%Y, %I:%M %p'),
            'error': True,
            'message': f"No se pudieron obtener las tasas BCV: {e}" # Añadir un mensaje de error
        }

# --- Endpoint API para Tasas (el frontend puede llamarlo) ---
@app.route('/api/tasas')
def api_tasas():
    """Proporciona las tasas BCV más recientes como JSON."""
    tasas = obtener_tasas_bcv() # Obtener datos frescos cada vez que se accede a este endpoint
    return jsonify(tasas)

# --- Configuración del Chat Gemini ---
# Inicialización segura del modelo
def get_chat_session():
    """Obtiene la sesión de chat del usuario, inicializándola si es necesario."""
    # Importante: Almacenar solo el historial en la sesión, no el objeto del modelo
    if 'chat_history' not in session:
        session['chat_history'] = []
    
    # Crear una nueva instancia del modelo e iniciar chat con el historial almacenado
    model = genai.GenerativeModel('gemini-2.0-flash')
    # Asegurarse de que el historial esté en el formato correcto para start_chat
    # El historial debe ser una lista de diccionarios: [{'role': 'user', 'parts': ['msg']}, {'role': 'model', 'parts': ['reply']}]
    # El historial de la sesión podría no estar en este formato exacto dependiendo de cómo se guardó previamente.
    # Un enfoque más seguro es simplemente pasar la lista de objetos de mensaje si la librería lo permite,
    # o construir manualmente la lista de diccionarios si es necesario.
    # Asumiendo que `session['chat_history']` almacena directamente objetos de mensaje:
    chat = model.start_chat(history=session['chat_history'])
    return chat

@app.before_request
def inicializar_datos():
    """Inicializa los datos financieros del usuario en la sesión."""
    # SOLO inicializar datos financieros aquí. Eliminar la obtención de tasas.
    if 'datos' not in session:
        session['datos'] = {
            'ingresos': 0,
            'gastos': {'Comida': 0, 'Transporte': 0, 'Vivienda': 0, 'Otros': 0},
            'deudas': 0,
            'ahorros': 0
        }
    # Asegurarse de que el historial del chat esté inicializado
    if 'chat_history' not in session:
         session['chat_history'] = []


@app.route('/')
def index():
    return redirect(url_for('registro'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        try:
            session['datos'] = {
                'ingresos': max(0, float(request.form.get('ingresos', 0))), # Usar .get con valor por defecto 0
                'gastos': {
                    'Comida': max(0, float(request.form.get('comida', 0))),
                    'Transporte': max(0, float(request.form.get('transporte', 0))),
                    'Vivienda': max(0, float(request.form.get('vivienda', 0))),
                    'Otros': max(0, float(request.form.get('otros', 0)))
                },
                'deudas': max(0, float(request.form.get('deudas', 0))),
                'ahorros': max(0, float(request.form.get('ahorros', 0)))
            }
            session.modified = True
            flash('Datos guardados exitosamente!', 'success') # Añadir un mensaje flash de éxito
        except ValueError:
            flash('Error: Ingresa solo valores numéricos válidos', 'danger') # Usar una categoría diferente para errores
        except Exception as e: # Capturar otros posibles errores
             flash(f'Error inesperado al guardar datos: {e}', 'danger')
        
        # Redirigir de vuelta a registro después de POST
        return redirect(url_for('registro'))
    
    # Para solicitud GET
    # Asegurarse de que se muestren valores por defecto si session['datos'] no está completamente poblado
    datos_para_template = session.get('datos', {
        'ingresos': 0,
        'gastos': {'Comida': 0, 'Transporte': 0, 'Vivienda': 0, 'Otros': 0},
        'deudas': 0,
        'ahorros': 0
    })
    # Asegurarse de que existan todas las claves en gastos para la plantilla
    for key in ['Comida', 'Transporte', 'Vivienda', 'Otros']:
        if key not in datos_para_template['gastos']:
            datos_para_template['gastos'][key] = 0

    return render_template('registro.html', datos=datos_para_template)


@app.route('/asistente')
def asistente():
    # Obtener tasas actuales para potencialmente mostrarlas en la página del asistente
    # O depender de JavaScript en el frontend para obtenerlas a través de /api/tasas
    # Vamos a obtenerlas aquí para hacerlas disponibles a la plantilla si es necesario
    tasas_actuales = obtener_tasas_bcv()
    return render_template('asistente.html', tasas=tasas_actuales)


@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(error):
    status_code = getattr(error, 'code', 500) # Obtener código de error, por defecto 500
    message = "Recurso no encontrado" if status_code == 404 else "Error interno del servidor"
    
    # Registrar el error del servidor
    if status_code == 500:
        import traceback
        print(f"Error Interno del Servidor: {error}")
        traceback.print_exc()

    return jsonify({
        "status": "error",
        "message": message,
        "details": str(error) if status_code != 404 else None # Incluir detalles del error para 500
    }), status_code

@app.route('/api/chat', methods=['POST'])
def chat_handler():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip() # Usar strip() para eliminar espacios en blanco iniciales/finales

        # Manejar primero las solicitudes de tasas de cambio
        rate_keywords = ['dólar', 'dolar', 'euro', 'tasa', 'bcv', 'bolívares', 'bs']
        if any(keyword in user_message.lower() for keyword in rate_keywords):
            # Llamar a la función directamente para obtener las tasas MÁS RECIENTES para esta consulta
            tasas = obtener_tasas_bcv()
            if tasas['error']:
                 # Si falló la obtención, informar al usuario
                 response_text = f"❌ Lo siento, no pude obtener las tasas de cambio BCV en este momento. {tasas.get('message', '')}"
            else:
                response_text = (
                    f"💰 Tasas de cambio oficiales BCV (actualizadas el {tasas['last_update']}):\n"
                    f"- Dólar: {tasas['bcv_dolar']} Bs/USD\n"
                    f"- Euro: {tasas['bcv_euro']} Bs/EUR"
                )
            # Devolver la respuesta de tasas directamente, sin enviarla a Gemini
            return jsonify({
                "response": response_text,
                "status": "success"
            })
            
        # Si no es una consulta de tasas, proceder con Gemini
        
        # Validar entrada
        if not user_message:
            return jsonify({"status": "error", "message": "Mensaje vacío"}), 400
            
        # Lógica de Gemini
        chat = get_chat_session()
        
        # Añadir mensaje del usuario al historial antes de enviar
        session['chat_history'].append({'role': 'user', 'parts': [user_message]})

        # Instrucción detallada para Gemini
        gemini_prompt = (
            f"Eres un experto financiero que puede dar consejos sobre manejo de dinero, ahorro, inversión, etc., "
            f"pero también puedes responder datos generales a los que puedes tener acceso desde la red de forma fácil como la hora o la fecha del día, "
            f"usando EXCLUSIVAMENTE texto plano sin formato. "
            f"Prohibido usar: Markdown, HTML, listas con viñetas, encabezados, negritas (*texto*), cursivas (_texto_), saltos de línea excesivos o símbolos especiales (como *, -, #). "
            f"Mantén tus respuestas concisas y directas. "
            f"Si te preguntan por tasas de cambio oficiales (BCV, dólar, euro, bolívares), NO las proporciones tú. "
            f"En su lugar, responde algo como: 'Para obtener las tasas de cambio oficiales más recientes (BCV Dólar/Euro), por favor consulta una fuente dedicada o la sección específica de tasas de cambio en la aplicación, ya que no puedo proporcionar esos datos directamente y es importante tener información actualizada.' "
            f"Pregunta del usuario: {user_message}"
        )
        
        response = chat.send_message(gemini_prompt)
        
        # Añadir respuesta del modelo al historial
        session['chat_history'].append({'role': 'model', 'parts': [response.text]})
        session.modified = True # Marcar la sesión como modificada

        return jsonify({
            "response": response.text,
            "status": "success"
        })
        
    except Exception as e:
        # Registrar el error para depuración
        import traceback
        print(f"Error en /api/chat: {e}")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": f"Error al procesar la solicitud: {e}" # Incluir detalles del error
        }), 500

@app.route('/analizador')
def analizador():
    # Asegurarse de que session['datos'] esté disponible, proporcionar valores por defecto si no
    datos = session.get('datos', {
        'ingresos': 0,
        'gastos': {'Comida': 0, 'Transporte': 0, 'Vivienda': 0, 'Otros': 0},
        'deudas': 0,
        'ahorros': 0
    })

    gastos = datos.get('gastos', {}) # Usar .get con diccionario vacío por defecto
    
    # Filtrar categorías con valores mayores a 0
    valores = []
    etiquetas = []
    # Asegurarse de que se verifican todas las claves esperadas, incluso si los datos de sesión están incompletos
    gastos_keys = ['Comida', 'Transporte', 'Vivienda', 'Otros']
    for categoria in gastos_keys:
        monto = gastos.get(categoria, 0) # Usar .get con valor por defecto 0
        if monto > 0:
            valores.append(monto)
            etiquetas.append(categoria)
    
    # Verificar si hay datos para graficar
    if not valores or sum(valores) == 0: # Verificar si la lista está vacía o la suma es cero
        plot_url = None
    else:
        # Generar gráfico de pastel
        img = BytesIO()
        plt.figure(figsize=(8, 8))
        plt.pie(valores, 
                labels=etiquetas,
                autopct='%1.1f%%',
                startangle=140,
                colors=plt.cm.Paired(range(len(valores)))) # Añadir algunos colores
        plt.title('Distribución de Gastos')
        plt.axis('equal') # La relación de aspecto igual asegura que el pastel se dibuje como un círculo.
        plt.tight_layout() # Ajustar diseño
        plt.savefig(img, format='png')
        plt.close() # Cerrar la figura del gráfico para liberar memoria
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
    
    # Regla 50/30/20 con validación
    ingresos = float(datos.get('ingresos', 0)) # Usar .get con valor por defecto 0
        
    presupuesto = {
        'necesidades': ingresos * 0.5,
        'deseos': ingresos * 0.3,
        'ahorro': ingresos * 0.2
    }

    return render_template('analizador.html', 
                           plot_url=plot_url,
                           presupuesto=presupuesto,
                           datos=datos) # Pasar datos completos a la plantilla si es necesario


# --- Ejecución Principal ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Ejecutar con debug=True es solo para desarrollo
    # En producción, solo usar app.run(host='0.0.0.0', port=port)
    # Para desarrollo local, puedes usar debug=True
    app.run(host='0.0.0.0', port=port, debug=True)
