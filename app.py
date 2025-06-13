from flask import Flask, render_template, request, session, redirect, url_for
from flask import jsonify # Redundante, ya estaba importado arriba, pero lo dejo como estaba
import google.generativeai as genai
from flask import flash
import requests
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')
from flask import Flask, session, request # Redundante, ya estaba importado arriba
import os
from flask_cors import CORS
from datetime import datetime # <-- Importar datetime

app = Flask(__name__)

# Añade esta ruta antes de las demás
@app.route('/api/tasas')
def obtener_tasas():
    # Obtener la fecha y hora actual ANTES de intentar la API externa
    # Usamos strftime para formatear la fecha/hora legiblemente
    fecha_actualizacion = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    try:
        # API no oficial del BCV (ejemplo)
        # Puedes validar la URL aquí si es necesario, o confiar en raise_for_status()
        response = requests.get('https://monitordolarvzla.com/api/v1/exchange_rates/latest', timeout=10) # Añadir timeout
        response.raise_for_status() # Lanza un error para códigos de estado HTTP 4xx/5xx

        data = response.json()

        # Validar si la estructura esperada existe en la respuesta
        # Usamos .get() con valor por defecto para evitar KeyError si alguna clave falta
        bcv_rate = data.get('data', {}).get('USD', {}).get('exchange_rates', {}).get('bcv')
        promedio_rate = data.get('data', {}).get('USD', {}).get('exchange_rates', {}).get('promedio')

        # Si las claves esperadas no existen o son None, tratamos como un error de la API
        if bcv_rate is None or promedio_rate is None:
             # Lanzamos un error específico para que caiga en el except y use los valores por defecto
             raise ValueError("Estructura de respuesta de la API inesperada")


        # Si todo fue bien, retornamos los datos de la API
        return jsonify({
            'bcv': bcv_rate,
            'promedio': promedio_rate,
            'fecha': fecha_actualizacion, # <-- Incluir la fecha
            'error': False # Indicar que NO hubo error al obtener tasas reales
        })

    # Manejar errores específicos de la solicitud HTTP (red, timeouts, etc.)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching external API: {e}") # Opcional: loguear el error en el servidor
        # Retornar los valores por defecto con la bandera de error
        return jsonify({
            'bcv': 92.83,  # Valores por defecto
            'promedio': 103.64,
            'error': True, # Indicar que hubo error y se usaron defaults
            'fecha': fecha_actualizacion # <-- Incluir la fecha
        })
    # Manejar errores al procesar el JSON (estructura incorrecta, claves faltantes, etc.)
    except (KeyError, ValueError) as e:
        print(f"Error processing API response JSON: {e}") # Loguear el error
        # Retornar los valores por defecto con la bandera de error
        return jsonify({
            'bcv': 92.83,  # Valores por defecto
            'promedio': 103.64,
            'error': True, # Indicar que hubo error y se usaron defaults
            'fecha': fecha_actualizacion # <-- Incluir la fecha
        })
    # Capturar cualquier otro error inesperado
    except Exception as e:
        print(f"An unexpected error occurred in /api/tasas: {e}") # Loguear el error
        # Retornar los valores por defecto con la bandera de error
        return jsonify({
            'bcv': 92.83,  # Valores por defecto
            'promedio': 103.64,
            'error': True, # Indicar que hubo error y se usaron defaults
            'fecha': fecha_actualizacion # <-- Incluir la fecha
        })

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
    # Es importante crear una nueva instancia del chat model *cada vez*
    # usando el historial de la sesión, no usar la instancia de la sesión directamente.
    # Corrijo esto aquí también.
    model = genai.GenerativeModel('gemini-2.0-flash')
    chat = model.start_chat(history=session.get('chat', [])) # Asegura un historial vacío si no existe
    # Actualizar el historial en la sesión después de enviar un mensaje (esto se hace en el handler POST)
    return chat


@app.before_request
def inicializar_datos():
    if 'datos' not in session:
        session['datos'] = {
            'ingresos': 0.0, # Usar float por defecto
            'gastos': {'Comida': 0.0, 'Transporte': 0.0, 'Vivienda': 0.0, 'Otros': 0.0}, # Usar float por defecto
            'deudas': 0.0, # Usar float por defecto
            'ahorros': 0.0 # Usar float por defecto
        }

@app.route('/')
def index():
    # Redirigir directamente a registro
    return redirect(url_for('registro'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    # Asegurar que session['datos'] existe antes de intentar acceder a ella
    if 'datos' not in session:
        inicializar_datos() # Llama a la función para inicializarla si no existe

    if request.method == 'POST':
        try:
            # Intenta convertir todos los valores a float antes de asignarlos
            ingresos = float(request.form.get('ingresos', 0)) # Usar .get() para evitar KeyError
            comida = float(request.form.get('comida', 0))
            transporte = float(request.form.get('transporte', 0))
            vivienda = float(request.form.get('vivienda', 0))
            otros = float(request.form.get('otros', 0))
            deudas = float(request.form.get('deudas', 0))
            ahorros = float(request.form.get('ahorros', 0))

            session['datos'] = {
                'ingresos': max(0.0, ingresos),
                'gastos': {
                    'Comida': max(0.0, comida),
                    'Transporte': max(0.0, transporte),
                    'Vivienda': max(0.0, vivienda),
                    'Otros': max(0.0, otros)
                },
                'deudas': max(0.0, deudas),
                'ahorros': max(0.0, ahorros)
            }
            session.modified = True # Asegurar que la sesión se guarda
            flash('Datos actualizados correctamente', 'success') # Añade mensaje de éxito
        except ValueError:
            flash('Error: Ingresa solo valores numéricos válidos.', 'danger') # Clase 'danger' para Bootstrap
        # No redirigir aquí si hubo error para mostrar el mensaje flash en la misma página con los datos ingresados (o re-cargados)
        # Si quieres redirigir incluso con error, descomenta la línea siguiente
        # return redirect(url_for('registro'))


    # En GET request o después de POST con/sin error, renderizar la plantilla
    # Asegúrate de pasar session['datos'] a la plantilla
    return render_template('registro.html', datos=session['datos'])

@app.route('/asistente')
def asistente():
    return render_template('asistente.html')

@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(error):
    # Si el error es un HTTPException (como 404), tiene un description y code
    status_code = getattr(error, 'code', 500)
    message = getattr(error, 'description', 'Error interno del servidor') if status_code != 404 else 'Recurso no encontrado'

    # Esto es más para una API REST. Si es una aplicación web, podrías querer renderizar una plantilla de error
    if request.path.startswith('/api/'):
         return jsonify({
            "status": "error",
            "message": message
        }), status_code
    else:
        # Para rutas no API, podrías renderizar una página de error HTML
        return render_template('error.html', status_code=status_code, message=message), status_code


@app.route('/api/chat', methods=['POST'])
def chat_handler():
    try:
        data = request.get_json()
        user_message = data.get('message', '')

        # Validar entrada
        if not user_message or not isinstance(user_message, str) or len(user_message.strip()) == 0:
            return jsonify({"status": "error", "message": "Mensaje vacío o inválido"}), 400

        chat = get_chat_session()

        # Intentar enviar el mensaje
        try:
            response = chat.send_message(
                f"Eres un asesor financiero personal. Responde de manera clara, concisa y útil EXCLUSIVAMENTE usando texto plano. "
                f"Prohibido usar: Markdown (*, #, -, >), HTML (<>), listas con viñetas (-, *), encabezados, o cualquier símbolo o formato especial que no sea texto simple. "
                f"Evita cualquier formato especial. Limítate a párrafos de texto plano."
                f"Pregunta del usuario: {user_message}"
            )
            # Actualizar el historial de la sesión *después* de una respuesta exitosa
            session['chat'] = chat.history
            session.modified = True

            # Validar si la respuesta tiene texto
            if not response or not hasattr(response, 'text') or not response.text:
                 return jsonify({
                    "status": "error",
                    "message": "La IA no pudo generar una respuesta de texto válida."
                 }), 500


            return jsonify({
                "response": response.text,
                "status": "success"
            })

        except Exception as ai_error:
             # Manejar errores específicos de la API de Gemini
             print(f"Error de la API de Gemini: {ai_error}")
             return jsonify({
                "status": "error",
                "message": f"Lo siento, hubo un error al comunicarme con la IA. Intenta de nuevo más tarde. Detalle: {ai_error}"
             }), 500


    except Exception as e:
        print(f"Error general en /api/chat: {e}")
        return jsonify({
            "status": "error",
            "message": "Error interno del servidor al procesar la solicitud del chat."
        }), 500


@app.route('/analizador')
def analizador():
    # Asegurar que session['datos'] existe antes de intentar acceder a ella
    if 'datos' not in session:
        inicializar_datos() # Llama a la función para inicializarla si no existe

    gastos = session['datos']['gastos']

    # Filtrar categorías con valores mayores a 0
    valores = []
    etiquetas = []
    for categoria, monto in gastos.items():
        # Convertir a float y manejar posibles errores (aunque antes_request ya lo hace)
        try:
            monto = float(monto)
        except (ValueError, TypeError):
            monto = 0.0 # Si no es un número válido, tratarlo como 0

        if monto > 0:
            valores.append(monto)
            etiquetas.append(categoria)

    # Verificar si hay datos para graficar
    # Sumar los valores para ver si el total de gastos es mayor a 0
    if sum(valores) == 0 or len(valores) == 0:
        plot_url = None
    else:
        # Generar gráfico de pastel
        img = BytesIO()
        plt.figure(figsize=(8, 8))
        # Añadir wedgeprops para un pequeño espacio entre slices
        plt.pie(valores,
                labels=etiquetas,
                autopct='%1.1f%%',
                startangle=140,
                wedgeprops=dict(width=0.4, edgecolor='white')) # Dona en lugar de pastel
        plt.title('Distribución de Gastos', fontsize=16) # Título más claro
        plt.axis('equal') # Equal aspect ratio ensures that pie is drawn as a circle.

        # Convertir a PNG y codificar
        plt.tight_layout() # Ajustar diseño
        plt.savefig(img, format='png')
        plt.close() # Cierra la figura para liberar memoria
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')

    # Regla 50/30/20 con validación
    try:
        ingresos = float(session['datos'].get('ingresos', 0)) # Usar .get() con default
    except (KeyError, ValueError, TypeError):
        ingresos = 0.0 # Default en caso de error

    presupuesto = {
        'necesidades': ingresos * 0.5,
        'deseos': ingresos * 0.3,
        'ahorro': ingresos * 0.2
    }
    # Asegurarse de que los valores no sean negativos (aunque max(0, ..) ya ayuda)
    presupuesto = {k: max(0.0, v) for k, v in presupuesto.items()}


    return render_template('analizador.html',
                         plot_url=plot_url,
                         presupuesto=presupuesto)

if __name__ == '__main__':
    # Es un error llamar a app.run dos veces.
    # La primera se ejecutará y bloqueará. La segunda nunca se alcanzará.
    # Mantén solo una llamada a app.run
    # app.run(host='0.0.0.0', port=port) # Esta ya incluye el host y puerto
    # app.run(debug=True) # Esto sobrescribe si se ejecuta, y sin host/port por defecto

    # Opción recomendada: Usar variables de entorno o un valor por defecto
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true' or os.environ.get('DEBUG', 'false').lower() == 'true'
    # En producción, DEBUG debería ser False
    # En desarrollo, puedes poner FLASK_DEBUG=true

    app.run(host='0.0.0.0', port=port, debug=debug_mode)