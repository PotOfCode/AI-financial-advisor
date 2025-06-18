from flask import Flask, render_template, request, session, redirect, url_for
from flask import jsonify
import google.generativeai as genai
from flask import flash
import requests
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)

app.secret_key = os.environ.get('SECRET_KEY')

CORS(app)  # Permite solicitudes desde cualquier origen

# Configuración de las APIs
# ** API para IA de Google **
GOOGLE_API_KEY = os.environ.get('GEMINI_API_KEY')
genai.configure(api_key=GOOGLE_API_KEY)

# ** API para Tasas de Cambio **
EXCHANGERATE_API_KEY = os.environ.get('CHANGE_API_KEY')

#* --- Configuración de la Base de Datos SQLite ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

    #* --- Modelos de Base de Datos ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(120), unique=True, nullable=False) # nullable=False significa que no puede ser nulo
    financial_data = db.relationship('FinancialData', backref='owner', uselist=False, lazy='joined')

class FinancialData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    ingresos = db.Column(db.Float, default=0.0, nullable=False)
    gasto_comida = db.Column(db.Float, default=0.0, nullable=False)
    gasto_transporte = db.Column(db.Float, default=0.0, nullable=False)
    gasto_vivienda = db.Column(db.Float, default=0.0, nullable=False)
    gasto_otros = db.Column(db.Float, default=0.0, nullable=False)
    deudas = db.Column(db.Float, default=0.0, nullable=False)
    ahorros = db.Column(db.Float, default=0.0, nullable=False)
    
    #* --- Fin de Modelos ---
#* --- Fin de Configuración de Base de Datos ---

# Rutas y Lógica de la Aplicación

@app.route('/api/tasas')
def obtener_tasas():
    # Obtener la fecha y hora actual al inicio
    fecha_actualizacion = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    # ** Lógica para obtener tasas de ExchangeRate-API **
    if not EXCHANGERATE_API_KEY:
        print("Advertencia: EXCHANGERATE_API_KEY no configurada. Usando valor por defecto.")
        return jsonify({
            'bcv': 92.83,
            'error': True,
            'fecha': fecha_actualizacion,
            'mensaje': 'API Key de tasas de cambio no configurada.'
        })

    # URL para obtener las tasas más recientes con USD como base
    api_url = f'https://v6.exchangerate-api.com/v6/{EXCHANGERATE_API_KEY}/latest/USD'

    try:
        # Añadir un timeout para no colgar la aplicación
        response = requests.get(api_url, timeout=10)
        response.raise_for_status() # Lanza un error si la respuesta HTTP es 4xx o 5xx

        data = response.json()

        # Validar la respuesta de ExchangeRate-API
        if data.get('result') != 'success':
            print(f"Error de la API ExchangeRate-API: {data.get('error-type', 'Unknown error')}")
            raise ValueError(f"API error: {data.get('error-type', 'Unknown error')}")

        # Obtener la tasa de VES (Bolívar Venezolano)
        ves_rate = data.get('conversion_rates', {}).get('VES')

        if ves_rate is None:
             raise ValueError("Tasa de VES no encontrada en la respuesta de la API")

        # Si todo fue bien, retornamos la tasa obtenida para "BCV"
        # Usaremos la fecha de actualización de la API si está disponible, sino la nuestra local
        api_update_time = data.get('time_last_update_utc') # Formato UTC de la API
        if api_update_time:
            # Intentar convertir a formato local si es posible o usarla tal cual
            try:
                # Convertir la fecha UTC a un objeto datetime y luego formatear
                dt_utc = datetime.strptime(api_update_time, '%a, %d %b %Y %H:%M:%S +0000')
                # Aquí podrías convertir a hora local si necesitas, pero usar UTC es seguro
                formatted_date = dt_utc.strftime('%d/%m/%Y %H:%M:%S')
            except ValueError:
                # Si el formato de fecha de la API cambia, usarlo tal cual o el local
                formatted_date = api_update_time
        else:
            formatted_date = fecha_actualizacion # Usar la fecha local si la API no la da o falla el parseo


        return jsonify({
            'bcv': ves_rate,      # Usamos la tasa de la API para BCV
            'fecha': formatted_date, # <-- Usar la fecha formateada (o UTC o local)
            'error': False,
            'mensaje': 'Tasas obtenidas de ExchangeRate-API.'
        })

    # Manejar errores específicos de la solicitud HTTP o de la API (invalid key, etc.)
    except requests.exceptions.RequestException as e:
        print(f"Error al conectar con ExchangeRate-API: {e}")
        return jsonify({
            'bcv': 92.83,  # Valor por defecto para BCV
            'error': True,
            'fecha': fecha_actualizacion, # Usar fecha local si falla la API
            'mensaje': f'Error al obtener tasas: {e}. Usando valor por defecto.'
        })
    # Manejar errores al procesar el JSON o al validar la respuesta de la API
    except (KeyError, ValueError, TypeError) as e: # Añadir TypeError por si algo no es del tipo esperado
        print(f"Error al procesar respuesta de ExchangeRate-API: {e}")
        return jsonify({
            'bcv': 92.83,  # Valor por defecto para BCV
            'error': True,
            'fecha': fecha_actualizacion, # Usar fecha local si falla la API
            'mensaje': f'Error al procesar respuesta de API: {e}. Usando valor por defecto.'
        })
    # Capturar cualquier otro error inesperado
    except Exception as e:
        print(f"Error inesperado en /api/tasas: {e}")
        return jsonify({
            'bcv': 92.83,
            'error': True,
            'fecha': fecha_actualizacion, # Usar fecha local si falla la API
            'mensaje': f'Error inesperado: {e}. Usando valor por defecto.'
        })

# Inicialización segura del modelo de Chat para Gemini
# ** ESTA SECCIÓN ES LA QUE SE REVIERTE AL ESTADO ANTERIOR **
def get_chat_session():
    # Si 'chat' (el historial) no está en la sesión, inicializa uno vacío
    if 'chat' not in session:
        model = genai.GenerativeModel('gemini-2.0-flash')
        # Inicia un chat nuevo con historial vacío y guarda el historial en la sesión
        # Flask session guarda objetos serializables. El historial del chat es una lista de objetos Content.
        session['chat'] = model.start_chat(history=[]).history
        # session.modified = True # No estrictamente necesario aquí, pero puede ayudar a asegurar que se guarda
    # Crea una *nueva* instancia del modelo y del chat, cargando el historial guardado
    # Esto es importante porque los objetos de chat de genai pueden no ser seguros para múltiples peticiones/hilos.
    model = genai.GenerativeModel('gemini-2.0-flash')
    chat = model.start_chat(history=session['chat']) # Carga el historial de la sesión
    # NOTA: Cuando chat.send_message se llama en chat_handler,
    # modifica el objeto 'chat.history' *en su lugar*.
    # Flask debería detectar que el objeto dentro de la sesión ha sido modificado
    # y guardar la sesión al final de la petición.
    return chat

@app.before_request
def load_user_and_data():
    default_identifier = 'usuario_unico_del_asesor'
    user = User.query.filter_by(identifier=default_identifier).first()
    if not user:
        try:
            user = User(identifier=default_identifier)
            db.session.add(user)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error al crear usuario por defecto: {e}")
            return

    financial_data = FinancialData.query.filter_by(user_id=user.id).first()

    if not financial_data:
        try:
            financial_data = FinancialData(
                user_id=user.id,
                ingresos=0.0,
                gasto_comida=0.0,
                gasto_transporte=0.0,
                gasto_vivienda=0.0,
                gasto_otros=0.0,
                deudas=0.0,
                ahorros=0.0
            )
            db.session.add(financial_data)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error al crear datos financieros iniciales: {e}")
            return

    session['current_user_id'] = user.id
    session.modified = True

@app.route('/')
def index():
    # Redirigir directamente a registro
    return redirect(url_for('registro'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    user_id = session.get('current_user_id') # Obtenemos el ID de la sesión
    user = User.query.get(user_id) # Buscamos el objeto User
    user_financial_data = user.financial_data

    if not user_financial_data:
        flash('Error interno: No se pudieron cargar tus datos financieros.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            ingresos = float(request.form.get('ingresos', 0.0))
            comida = float(request.form.get('comida', 0.0))
            transporte = float(request.form.get('transporte', 0.0))
            vivienda = float(request.form.get('vivienda', 0.0))
            otros = float(request.form.get('otros', 0.0))
            deudas = float(request.form.get('deudas', 0.0))
            ahorros = float(request.form.get('ahorros', 0.0))

            user_financial_data.ingresos = max(0.0, ingresos)
            user_financial_data.gasto_comida = max(0.0, comida)
            user_financial_data.gasto_transporte = max(0.0, transporte)
            user_financial_data.gasto_vivienda = max(0.0, vivienda)
            user_financial_data.gasto_otros = max(0.0, otros)
            user_financial_data.deudas = max(0.0, deudas)
            user_financial_data.ahorros = max(0.0, ahorros)

            db.session.commit()
            flash('Datos actualizados correctamente', 'success')
        except ValueError:
            flash('Error: Ingresa solo valores numéricos válidos.', 'danger')
            db.session.rollback()

        except Exception as e:
            db.session.rollback() # IMPORTANTE: Deshacer cambios pendientes si hay un error
            flash(f'Error al guardar datos: {e}', 'danger')

    # En GET request o después de POST, renderizar la plantilla con los datos actuales de la sesión
    return render_template('registro.html', datos=user_financial_data) # Usar .get con default {} por si acaso

@app.route('/asistente')
def asistente():
    return render_template('asistente.html')

@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(error):
    # Obtener código y descripción del error, si es un HTTPException
    status_code = getattr(error, 'code', 500)
    description = getattr(error, 'description', 'Error interno del servidor')

    # Manejar errores 404 específicamente si la descripción es la por defecto
    if status_code == 404 and description == 'Not Found':
        message = 'Recurso no encontrado'
    else:
        message = description

    # Si la ruta es una API, retornar JSON
    if request.path.startswith('/api/'):
         return jsonify({
            "status": "error",
            "message": message
        }), status_code
    else:
        # Para rutas HTML, renderizar una página de error simple
        # Asegúrate de tener un template llamado 'error.html' o similar
        # Si no tienes error.html, puedes retornar un string o renderizar otra plantilla
        try:
            return render_template('error.html', status_code=status_code, message=message), status_code
        except Exception:
            # Fallback si error.html no existe
            return f"Error {status_code}: {message}", status_code


@app.route('/api/chat', methods=['POST'])
def chat_handler():
    try:
        data = request.get_json()
        user_message = data.get('message', '')

        # Validar entrada: debe ser string no vacío
        if not user_message or not isinstance(user_message, str) or len(user_message.strip()) == 0:
            return jsonify({"status": "error", "message": "Mensaje vacío o inválido"}), 400

        chat = get_chat_session() # Obtiene la sesión de chat cargada con el historial

        # Instrucciones para la IA
        # Mantuve las instrucciones mejoradas para que responda en texto plano
        prompt_instructions = (
            "Eres un asesor financiero personal y amigable. Tu objetivo es proporcionar consejos y explicaciones sobre finanzas personales, presupuestos, ahorros, deudas e inversiones de manera clara y fácil de entender."
            "Responde a las preguntas del usuario EXCLUSIVAMENTE usando texto plano."
            "Prohibido usar cualquier tipo de formato: Markdown (*, #, -, >, `), HTML (<>), listas (con viñetas o numeradas), encabezados, negritas, cursivas, o cualquier símbolo especial."
            "Limítate a párrafos de texto simple."
            "No te inventes información; si no sabes algo, dilo amablemente."
            "Pregunta del usuario: "
        )

        # Intentar enviar el mensaje a la IA
        try:
            response = chat.send_message(prompt_instructions + user_message)

            # Validar si la respuesta tiene texto
            if not response or not hasattr(response, 'text') or not response.text:
                 print(f"La IA no devolvió texto: {response}")
                 return jsonify({
                    "status": "error",
                    "message": "La IA no pudo generar una respuesta de texto válida."
                 }), 500

            # ** REVERTIDO: No actualizamos explícitamente session['chat'] aquí. **
            # Confiamos en que Flask detecte la modificación en chat.history (que es una referencia al objeto en la sesión)
            # y guarde la sesión automáticamente al final de la petición.

            return jsonify({
                "response": response.text,
                "status": "success"
            })

        # Capturar errores específicos de la interacción con la API de Gemini
        except Exception as ai_error:
             print(f"Error de la API de Gemini al enviar mensaje: {ai_error}")
             return jsonify({
                "status": "error",
                "message": f"Lo siento, hubo un error al procesar tu solicitud con la IA. Por favor, intenta de nuevo más tarde. (Detalle: {ai_error})"
             }), 500


    # Capturar errores generales (ej. JSON malformado, otros problemas no relacionados con la IA)
    except Exception as e:
        print(f"Error general en /api/chat: {e}")
        return jsonify({
            "status": "error",
            "message": "Error interno del servidor al procesar la solicitud."
        }), 500


@app.route('/analizador')
def analizador():
    user_id = session.get('current_user_id')
    user = User.query.get(user_id)
    user_financial_data = user.financial_data

    if not user_financial_data:

        flash('Por favor, registra tus datos financieros primero.', 'info')
        return redirect(url_for('registro'))

    gastos = {
    'Comida': user_financial_data.gasto_comida,
    'Transporte': user_financial_data.gasto_transporte,
    'Vivienda': user_financial_data.gasto_vivienda,
    'Otros': user_financial_data.gasto_otros
    }
    ingresos = user_financial_data.ingresos # Obtener ingresos de la DB

    valores = []
    etiquetas = []
    for categoria, monto in gastos.items():
        if monto > 0:
            valores.append(monto)
            etiquetas.append(categoria)

        plot_url = None
        if valores:
            # Generar gráfico de pastel (versión original simple)
            img = BytesIO()
            plt.figure(figsize=(8, 8))
            plt.pie(valores, labels=etiquetas, autopct='%1.1f%%', startangle=140)
            plt.title('Distribución de Gastos')
            plt.axis('equal')
            plt.savefig(img, format='png')
            plt.close()
            img.seek(0)
            plot_url = base64.b64encode(img.getvalue()).decode('utf8')

        presupuesto = {
            'necesidades': ingresos * 0.5,
            'deseos': ingresos * 0.3,
            'ahorro': ingresos * 0.2
        }
        presupuesto = {k: max(0.0, v) for k, v in presupuesto.items()}


    return render_template('analizador.html',
                        plot_url=plot_url,
                        presupuesto=presupuesto)

if __name__ == '__main__':
    # Configuración de host y puerto, y modo debug desde variables de entorno
    port = int(os.environ.get('PORT', 5000))
    # Debug es True si la variable FLASK_DEBUG o DEBUG está 'true' (case-insensitive)
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true' or \
                 os.environ.get('DEBUG', 'false').lower() == 'true'

    # Ejecutar la aplicación
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
