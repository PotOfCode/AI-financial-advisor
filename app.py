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