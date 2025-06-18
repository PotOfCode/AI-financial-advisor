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
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user # Importar Flask-Login
from werkzeug.security import generate_password_hash, check_password_hash
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
database_url = os.environ.get('DATABASE_URL')
if database_url is None:
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

#* --- Configuración de Flask-Login ---
login_manager = LoginManager() # Crea una instancia de LoginManager
login_manager.init_app(app)    # Vincula LoginManager a tu app Flask
login_manager.login_view = 'login' # Especifica el nombre de la función (ruta) de login para redirecciones automáticas
login_manager.login_message = 'Por favor, inicia sesión para acceder a esta página.' # Mensaje flash si se requiere login
login_manager.login_message_category = 'info' # Categoría del mensaje flash

# Función requerida por Flask-Login para recargar el objeto User a partir del user_id almacenado en la sesión
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

    #* --- Modelos de Base de Datos ---

# Modelo para el usuario
# Hereda de UserMixin para integrarse con Flask-Login
class User(UserMixin, db.Model): # <-- Añadir UserMixin
    id = db.Column(db.Integer, primary_key=True) # Clave primaria
    # Cambiamos 'identifier' a 'username' (o podrías usar 'email' y validar formato)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True) # El nombre de usuario para login
    password_hash = db.Column(db.String(128), nullable=False) # Campo para almacenar la contraseña hasheada

    # Relación con FinancialData (sin cambios aquí)
    financial_data = db.relationship('FinancialData', backref='owner', uselist=False, lazy='joined')

    # Método para hashear la contraseña antes de guardarla
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Método para verificar una contraseña ingresada contra el hash almacenado
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Representación (sin cambios)
    def __repr__(self):
        return f"<User {self.username}>"

class FinancialData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    ingresos = db.Column(db.Float, default=0.0, nullable=False)
    gasto_comida = db.Column(db.Float, default=0.0, nullable=False)
    gasto_transporte = db.Column(db.Float, default=0.0, nullable=False)
    gasto_vivienda = db.Column(db.Float, default=0.0, nullable=False)
    gasto_otros = db.Column(db.Float, default=0.0, nullable=False)
    deudas = db.Column(db.Float, default=0.0, nullable=False)
    ahorros = db.Column(db.Float, default=0.0, nullable=False)
    
    def __repr__(self):
        return f"<FinancialData ID:{self.id} for User {self.user_id}>"

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

@app.route('/')
def index():
    # Redirigir directamente a registro
    return redirect(url_for('registro'))

@app.route('/registro', methods=['GET', 'POST'])
@login_required
def registro():
    user_financial_data = current_user.financial_data

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
@login_required
def asistente():
    user_financial_data = current_user.financial_data
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
@login_required
def chat_handler():
    try:
        data = request.get_json()
        user_message = data.get('message', '')

        if not user_message or not isinstance(user_message, str) or len(user_message.strip()) == 0:
            return jsonify({"status": "error", "message": "Mensaje vacío o inválido"}), 400

        chat = get_chat_session() # Obtiene la sesión de chat cargada con el historial

        # Obtener datos financieros del usuario ACTUALMENTE LOGUEADO para contexto
        user_financial_data = current_user.financial_data # Accede a los datos del usuario logueado

        financial_context = ""
        if user_financial_data: # Solo si existen datos
             financial_context = (
                f"Aquí están los datos financieros actuales del usuario (Ingresos/Gastos/Deudas/Ahorros): "
                f"Ingresos: {user_financial_data.ingresos}, "
                f"Gastos Comida: {user_financial_data.gasto_comida}, "
                f"Gastos Transporte: {user_financial_data.gasto_transporte}, "
                f"Gastos Vivienda: {user_financial_data.gasto_vivienda}, "
                f"Gastos Otros: {user_financial_data.gasto_otros}, "
                f"Deudas Totales: {user_financial_data.deudas}, "
                f"Ahorros Actuales: {user_financial_data.ahorros}. "
                f"Considera esta información si es relevante para responder la pregunta del usuario, pero mantén tus respuestas en texto plano."
            )

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
            full_prompt = prompt_instructions + user_message
            response = chat.send_message(full_prompt)

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
@login_required
def analizador():
    user_financial_data = current_user.financial_data

    if not user_financial_data:
        flash('Error interno: No se pudieron cargar tus datos financieros. Intenta registrar tus datos de nuevo.', 'danger')
        # Quizás redirigir a registro o mostrar página de error específica
        return redirect(url_for('registro'))

    gastos = {
        'Comida': user_financial_data.gasto_comida,
        'Transporte': user_financial_data.gasto_transporte,
        'Vivienda': user_financial_data.gasto_vivienda,
        'Otros': user_financial_data.gasto_otros
    }
    ingresos = user_financial_data.ingresos

    valores = []
    etiquetas = []
    for categoria, monto in gastos.items():
        if monto > 0:
            valores.append(monto)
            etiquetas.append(categoria)

    plot_url = None # Inicializa plot_url fuera del bucle
    if valores: # Genera la gráfica solo si hay valores > 0
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

# --- Ruta para Registro de Nuevos Usuarios ---
@app.route('/registro_usuario', methods=['GET', 'POST'])
def registro_usuario():
    # Si el usuario ya está logueado, no tiene sentido que se registre de nuevo, redirigir
    if current_user.is_authenticated:
        flash('Ya has iniciado sesión.', 'info')
        return redirect(url_for('registro')) # O donde quieras redirigir a usuarios logueados

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password') # Contraseña en texto plano del formulario

        # --- Validación Básica del Formulario ---
        if not username or not password:
            flash('Username y password son requeridos.', 'danger')
            # Vuelve a renderizar el template, pasando el username para que el usuario no lo tenga que escribir de nuevo
            return render_template('registro_usuario.html', username=username)

        # --- Verificar si el username ya existe en la DB ---
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('El username ya existe. Por favor, elige otro.', 'danger')
            return render_template('registro_usuario.html', username=username)

        # --- Crear Nuevo Usuario y sus Datos Financieros Iniciales ---
        try:
            # Crea una nueva instancia del modelo User
            new_user = User(username=username)
            # Hashea la contraseña ANTES de asignarla al modelo
            new_user.set_password(password) # Usando el método que añadimos al modelo

            # Añadir el nuevo usuario a la sesión de la base de datos y guardarlo
            # Hacemos commit aquí para que el nuevo usuario tenga un 'id' asignado antes de crear FinancialData
            db.session.add(new_user)
            db.session.commit()

            # Crea la entrada de FinancialData vinculada al nuevo usuario
            initial_financial_data = FinancialData(
                user_id=new_user.id, # Usa el ID del usuario recién creado
                ingresos=0.0,
                gasto_comida=0.0, gasto_transporte=0.0,
                gasto_vivienda=0.0, gasto_otros=0.0,
                deudas=0.0, ahorros=0.0
            )
            db.session.add(initial_financial_data)
            db.session.commit() # Guarda los datos financieros iniciales

            flash('Registro exitoso. ¡Ya puedes iniciar sesión!', 'success')
            return redirect(url_for('login')) # Redirige a la página de login después del registro exitoso

        except Exception as e:
            # Si ocurre algún error (ej. error de DB), deshace los cambios y muestra un mensaje
            db.session.rollback()
            flash(f'Error al registrar usuario: {e}', 'danger')
            # app.logger.error(f"Error registering user: {e}")
            return render_template('registro_usuario.html', username=username)


    # Método GET: Simplemente muestra el formulario de registro
    return render_template('registro_usuario.html')

# --- Ruta para Inicio de Sesión ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Si el usuario ya está logueado, redirigir
    if current_user.is_authenticated:
        flash('Ya has iniciado sesión.', 'info')
        return redirect(url_for('registro')) # O donde quieras redirigir

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # --- Validación Básica del Formulario ---
        if not username or not password:
            flash('Nombre de usuario y contraseña son requeridos.', 'danger')
            return render_template('login.html', username=username) # Pasar username de vuelta

        # --- Buscar Usuario en la DB ---
        user = User.query.filter_by(username=username).first()

        # --- Verificar Usuario y Contraseña ---
        if user and user.check_password(password): # check_password_hash se llama dentro del método del modelo
            login_user(user) # Usa Flask-Login para iniciar la sesión del usuario
            flash('¡Inicio de sesión exitoso!', 'success')

            # Redirigir al usuario a la página que intentaba acceder antes de requerir login
            # Flask-Login guarda la URL original en request.args.get('next')
            next_page = request.args.get('next')
            # Si no hay 'next' (ej. fue directo a /login), redirige a una página por defecto
            return redirect(next_page or url_for('registro')) # Redirige al registro después de login

        else:
            # Si la verificación falla
            flash('Nombre de usuario o contraseña incorrectos.', 'danger')
            return render_template('login.html', username=username) # Vuelve a renderizar con error

    # Método GET: Simplemente muestra el formulario de login
    return render_template('login.html')

# --- Ruta para Cierre de Sesión ---
@app.route('/logout')
@login_required # Solo puedes cerrar sesión si ya estás logueado
def logout():
    logout_user() # Usa Flask-Login para cerrar la sesión
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('login')) # Redirige a la página de login o inicio

if __name__ == '__main__':
    # Configuración de host y puerto, y modo debug desde variables de entorno
    port = int(os.environ.get('PORT', 5000))
    # Debug es True si la variable FLASK_DEBUG o DEBUG está 'true' (case-insensitive)
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true' or \
                 os.environ.get('DEBUG', 'false').lower() == 'true'

    # Ejecutar la aplicación
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
