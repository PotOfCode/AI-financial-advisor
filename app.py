from flask import Flask, render_template, request, session, redirect, url_for
from flask import Flask, render_template, request, jsonify
import requests
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')
from flask import Flask, session, request
import os

app = Flask(__name__)
#app.secret_key = os.environ.get('SECRET_KEY')
app.secret_key = 'IL4LbtIP4r'


@app.before_request
def inicializar_datos():
    if 'datos' not in session:
        session['datos'] = {
            'ingresos': 0,
            'gastos': {'Comida': 0, 'Transporte': 0, 'Vivienda': 0, 'Otros': 0},
            'deudas': 0,
            'ahorros': 0
        }

@app.route('/')
def index():
    return redirect(url_for('registro'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        # Actualizar datos de sesión
        session['datos'] = {
            'ingresos': float(request.form['ingresos']),
            'gastos': {
                'Comida': float(request.form['comida']),
                'Transporte': float(request.form['transporte']),
                'Vivienda': float(request.form['vivienda']),
                'Otros': float(request.form['otros'])
            },
            'deudas': float(request.form['deudas']),
            'ahorros': float(request.form['ahorros'])
        }
        session.modified = True
        return redirect(url_for('registro'))
    
    return render_template('registro.html', datos=session['datos'])

@app.route('/asistente')
def asistente():
    consejos = {
        'ahorro': [
            "Automatiza transferencias a ahorros cada mes",
            "Reduce gastos pequeños recurrentes (cafés, snacks)"
        ],
        'deuda': [
            "Paga primero las deudas con mayor interés",
            "Considera consolidar deudas"
        ]
    }
    return render_template('asistente.html', consejos=consejos)

@app.route('/analizador')
def analizador():
    # Generar gráfico de pastel
    img = BytesIO()
    gastos = session['datos']['gastos']
    plt.figure(figsize=(6,6))
    plt.pie(gastos.values(), labels=gastos.keys(), autopct='%1.1f%%')
    plt.title('Distribución de Gastos')
    plt.savefig(img, format='png')
    plt.close()
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode('utf8')
    
    # Regla 50/30/20
    ingresos = session['datos']['ingresos']
    presupuesto = {
        'necesidades': ingresos * 0.5,
        'deseos': ingresos * 0.3,
        'ahorro': ingresos * 0.2
    }
    
    return render_template('analizador.html', 
                         plot_url=plot_url,
                         presupuesto=presupuesto)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    app.run(debug=True)