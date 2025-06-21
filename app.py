from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
import os
from dotenv import load_dotenv
load_dotenv()
import sys
import threading
import io
import tkinter as tk
from tkinter import ttk
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from decimal import Decimal
import json
from functools import wraps
from month_transition import check_and_transfer_previous_month_balance

# Configurar logging
class TkinterLogHandler(logging.Handler):
    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.see(tk.END)
        # Programar a inserção na thread principal do Tkinter
        self.text_widget.after(0, append)

# Inicializar o Flask antes de configurar o logging
app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
app.secret_key = os.urandom(24)

# Context processor to provide date to all templates
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# Database connection
def get_db_connection():
    connection = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    return connection

# Custom JSON encoder for handling dates and decimals
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

app.json_encoder = CustomJSONEncoder

# Authentication middleware
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, faça login para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped_view

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        full_name = request.form['full_name']
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Check if username or email already exists
        cursor.execute('SELECT * FROM users WHERE username = %s OR email = %s', (username, email))
        user = cursor.fetchone()
        
        if user:
            flash('Nome de usuário ou e-mail já existe.', 'danger')
        else:
            # Hash the password
            hashed_password = generate_password_hash(password)
            
            # Insert new user
            cursor.execute(
                'INSERT INTO users (username, password, email, full_name) VALUES (%s, %s, %s, %s)',
                (username, hashed_password, email, full_name)
            )
            conn.commit()
            
            flash('Registro realizado com sucesso! Faça login para continuar.', 'success')
            return redirect(url_for('login'))
        
        cursor.close()
        conn.close()
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Usuário ou senha inválidos.', 'danger')
        
        cursor.close()
        conn.close()
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você foi desconectado com sucesso!', 'success')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get user data
    cursor.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
    user = cursor.fetchone()
    
    if request.method == 'POST':
        # Update user's full name
        full_name = request.form['full_name']
        
        # Check if password change was requested
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Update user's full name
        if full_name != user['full_name']:
            cursor.execute('UPDATE users SET full_name = %s WHERE id = %s', 
                          (full_name, session['user_id']))
            conn.commit()
            session['full_name'] = full_name
            flash('Nome atualizado com sucesso!', 'success')
        
        # Update password if provided
        if current_password and new_password and confirm_password:
            # Verify current password
            if check_password_hash(user['password'], current_password):
                # Check if new passwords match
                if new_password == confirm_password:
                    # Hash the new password
                    hashed_password = generate_password_hash(new_password)
                    
                    # Update password in database
                    cursor.execute('UPDATE users SET password = %s WHERE id = %s', 
                                  (hashed_password, session['user_id']))
                    conn.commit()
                    flash('Senha atualizada com sucesso!', 'success')
                else:
                    flash('As novas senhas não coincidem.', 'danger')
            else:
                flash('Senha atual incorreta.', 'danger')
        
        # Refresh user data
        cursor.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
        user = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template('profile.html', user=user)

@app.route('/dashboard')
@login_required
def dashboard():
    # Check if the month has changed and transfer the previous month's balance if needed
    transfer_result = check_and_transfer_previous_month_balance(session['user_id'])
    if transfer_result:
        flash('Saldo do mês anterior transferido automaticamente como receita.', 'success')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get recent expenses
    try:
        cursor.execute('''
            SELECT e.*, c.name as category_name 
            FROM expenses e 
            JOIN expense_categories c ON e.category_id = c.id 
            WHERE e.user_id = %s 
            ORDER BY e.date DESC LIMIT 5
        ''', (session['user_id'],))
        recent_expenses = cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error retrieving expenses: {err}")
        recent_expenses = []
    
    # Get recent investments
    try:
        cursor.execute('''
            SELECT i.*, t.name as type_name 
            FROM investments i 
            JOIN investment_types t ON i.type_id = t.id 
            WHERE i.user_id = %s 
            ORDER BY i.date DESC LIMIT 5
        ''', (session['user_id'],))
        recent_investments = cursor.fetchall()
    except mysql.connector.Error as err:
        # Handle the case when the table doesn't exist or has no data
        print(f"Error retrieving investments: {err}")
        recent_investments = []
    
    # Get monthly expense summary
    try:
        # Obter o mês e ano atual
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        # Consulta para despesas normais (não recorrentes e não parceladas)
        cursor.execute('''
            SELECT SUM(amount) as total, MONTH(date) as month, YEAR(date) as year
            FROM expenses
            WHERE user_id = %s 
              AND MONTH(date) = %s
              AND YEAR(date) = %s
              AND (is_recurring = FALSE OR is_recurring IS NULL)
              AND (is_installment = FALSE OR is_installment IS NULL)
            GROUP BY YEAR(date), MONTH(date)
        ''', (session['user_id'], current_month, current_year))
        regular_expenses = cursor.fetchall()
        
        # Buscar todas as despesas parceladas para processamento manual
        cursor.execute('''
            SELECT id, description, amount, date, total_installments
            FROM expenses
            WHERE user_id = %s AND is_installment = TRUE
        ''', (session['user_id'],))
        installment_expenses_raw = cursor.fetchall()
        
        # Inicializar o total de despesas parceladas para o mês atual
        total_installment = 0
        
        # Data atual para comparações
        today = datetime.now().date()
        current_month_year = f"{current_year}-{current_month:02d}"
        
        print(f"DEBUG - Processando despesas parceladas para o mês/ano: {current_month_year}")
        
        # Abordagem completamente nova para cálculo de despesas parceladas
        print(f"DEBUG - TOTAL DE DESPESAS PARCELADAS ENCONTRADAS: {len(installment_expenses_raw)}")
        
        # Lista para armazenar todas as parcelas do mês atual
        current_month_installments = []
        
        for expense in installment_expenses_raw:
            expense_id = expense['id']
            expense_desc = expense['description']
            expense_amount = float(expense['amount'])
            expense_date = expense['date']
            total_installments = expense['total_installments']
            
            # Calcular o valor de cada parcela
            installment_amount = expense_amount / total_installments
            
            print(f"DEBUG - Analisando despesa parcelada: {expense_desc}, Valor: {expense_amount}, Data: {expense_date}, Parcelas: {total_installments}")
            
            # Gerar todas as datas de parcelas
            installment_dates = []
            for i in range(total_installments):
                month_offset = i
                installment_year = expense_date.year + ((expense_date.month - 1 + month_offset) // 12)
                installment_month = ((expense_date.month - 1 + month_offset) % 12) + 1
                installment_day = min(expense_date.day, 28)  # Evitar problemas com meses de diferentes durações
                installment_date = datetime(installment_year, installment_month, installment_day).date()
                installment_dates.append((i+1, installment_date))
            
            # Verificar quais parcelas pertencem ao mês atual
            for installment_num, installment_date in installment_dates:
                if installment_date.month == current_month and installment_date.year == current_year:
                    current_month_installments.append({
                        'description': expense_desc,
                        'installment_num': installment_num,
                        'total_installments': total_installments,
                        'amount': installment_amount,
                        'date': installment_date
                    })
                    print(f"DEBUG - ENCONTRADA parcela {installment_num}/{total_installments} de {expense_desc} para o mês atual: R$ {installment_amount:.2f} (Data: {installment_date})")
        
        # Calcular o total de todas as parcelas do mês atual
        total_installment = sum(item['amount'] for item in current_month_installments)
        
        # Exibir detalhes de cada parcela contabilizada
        print(f"DEBUG - PARCELAS CONTABILIZADAS PARA {current_month}/{current_year}:")
        for item in current_month_installments:
            print(f"  - {item['description']}: Parcela {item['installment_num']}/{item['total_installments']} - R$ {item['amount']:.2f} (Data: {item['date']})")
        
        print(f"DEBUG - TOTAL DE PARCELAS ENCONTRADAS PARA O MÊS ATUAL: {len(current_month_installments)}")
        print(f"DEBUG - VALOR TOTAL DAS PARCELAS DO MÊS ATUAL: R$ {total_installment:.2f}")        
        # Criar um objeto com o total de despesas parceladas para o mês atual
        installment_expenses = [{'total': total_installment}]
        print(f"DEBUG - Total de despesas parceladas após processamento: {total_installment:.2f}")
        print(f"DEBUG - RESUMO: Encontradas {len(installment_expenses_raw)} despesas parceladas, total calculado para o mês {current_month}/{current_year}: R$ {total_installment:.2f}")
        
        # Consulta para despesas recorrentes
        cursor.execute('''
            SELECT 
                SUM(amount) as total,
                %s as month,
                %s as year
            FROM expenses
            WHERE user_id = %s 
              AND is_recurring = TRUE
              AND (
                  -- Despesas recorrentes de meses anteriores
                  (date <= CURRENT_DATE() AND (recurring_end_date IS NULL OR recurring_end_date >= CURRENT_DATE()))
                  OR
                  -- Despesas recorrentes cadastradas no mês atual, mas com data futura
                  (MONTH(date) = %s AND YEAR(date) = %s AND date > CURRENT_DATE())
              )
              AND (
                  (recurring_type = 'monthly') OR
                  (recurring_type = 'yearly' AND MONTH(date) = %s) OR
                  (recurring_type = 'weekly')
              )
        ''', (current_month, current_year, session['user_id'], current_month, current_year, current_month))
        recurring_expenses = cursor.fetchall()
        
        # Inicializar os totais para o mês atual (exceto parcelas que já foram calculadas)
        total_regular = 0
        total_recurring = 0
        # Não reinicializar total_installment, pois já foi calculado acima
        
        # Somar despesas regulares
        if regular_expenses and len(regular_expenses) > 0 and regular_expenses[0]['total'] is not None:
            total_regular = float(regular_expenses[0]['total'])
        
        # Somar despesas recorrentes
        if recurring_expenses and len(recurring_expenses) > 0 and recurring_expenses[0]['total'] is not None:
            total_recurring = float(recurring_expenses[0]['total'])
        
        # O total de despesas parceladas já foi calculado acima
        print(f"DEBUG - Total de despesas parceladas calculado manualmente: {total_installment:.2f}")
        
        # Garantir que o valor das despesas parceladas seja considerado no total
        installment_expenses = [{'total': total_installment}]
        
        # Calcular o total geral para o mês atual
        total_month = float(total_regular) + float(total_recurring) + float(total_installment)
        print(f"DEBUG - Total regular: {total_regular}")
        print(f"DEBUG - Total recorrente: {total_recurring}")
        print(f"DEBUG - Total parcelado: {total_installment}")
        print(f"DEBUG - Total do mês: {total_month}")
        
        # Criar a entrada para o mês atual
        monthly_expenses = [{
            'total': float(total_month),
            'month': int(current_month),
            'year': int(current_year)
        }]
        
        # Garantir que o valor seja exibido corretamente no dashboard
        print(f"DEBUG - monthly_expenses antes de enviar para o template: {monthly_expenses}")
        
        # Forçar o valor total para garantir que seja exibido corretamente
        total_expenses_value = float(total_month)
        
        # Garantir que o valor seja um float válido
        if isinstance(monthly_expenses[0]['total'], float):
            print(f"Total mensal é um float válido: {monthly_expenses[0]['total']}")
        else:
            print(f"ERRO: Total mensal não é um float válido: {type(monthly_expenses[0]['total'])}")
            monthly_expenses[0]['total'] = float(monthly_expenses[0]['total'] or 0)
        
        # Imprimir para debug
        print(f"Mês atual: {current_month}/{current_year}")
        print(f"Total regular: {total_regular}")
        print(f"Total recorrente: {total_recurring}")
        print(f"Total parcelado: {total_installment}")
        print(f"Total geral: {total_month}")
        
        # Ordenar por ano e mês
        monthly_expenses = sorted(monthly_expenses, key=lambda x: (x['year'], x['month']))
        
    except mysql.connector.Error as err:
        print(f"Error retrieving monthly expenses: {err}")
        monthly_expenses = []
    
    # Get monthly income summary
    try:
        # Obter o mês e ano atual
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        cursor.execute('''
            SELECT SUM(amount) as total, %s as month, %s as year
            FROM income
            WHERE user_id = %s 
              AND MONTH(date) = %s
              AND YEAR(date) = %s
        ''', (current_month, current_year, session['user_id'], current_month, current_year))
        income_result = cursor.fetchone()
        
        # Inicializar o total de receitas
        total_income = 0
    except mysql.connector.Error as err:
        print(f"Error retrieving monthly income summary: {err}")
        income_result = None
        total_income = 0
    # Get total investments
    try:
        cursor.execute('''
            SELECT SUM(amount) as total 
            FROM investments 
            WHERE user_id = %s
        ''', (session['user_id'],))
        result = cursor.fetchone()
        total_investments = result['total'] if result and result['total'] else 0
    except mysql.connector.Error as err:
        print(f"Error retrieving total investments: {err}")
        total_investments = 0
    
    # Get monthly expenses for current month - we already calculated this above
    # We're keeping the variable name monthly_expenses from the detailed calculation above
    # No need to recalculate it here
    
    # Store the calculated monthly expenses in a separate variable for the template
    calculated_monthly_expenses = monthly_expenses
    
    # Get monthly income for current month
    try:
        cursor.execute('''
            SELECT SUM(amount) as total 
            FROM income 
            WHERE user_id = %s AND MONTH(date) = %s AND YEAR(date) = %s
        ''', (session['user_id'], current_month, current_year))
        result = cursor.fetchone()
        monthly_income = [{'total': result['total'] if result and result['total'] else 0}]
    except mysql.connector.Error as err:
        print(f"Error retrieving monthly income: {err}")
        monthly_income = [{'total': 0}]
        
    # Get today's expenses
    try:
        today = datetime.now().date()
        
        # Consulta para despesas normais (não recorrentes e não parceladas) de hoje
        cursor.execute('''
            SELECT SUM(amount) as total 
            FROM expenses 
            WHERE user_id = %s AND DATE(date) = %s
            AND (is_recurring = FALSE OR is_recurring IS NULL)
            AND (is_installment = FALSE OR is_installment IS NULL)
        ''', (session['user_id'], today))
        regular_today = cursor.fetchone()
        total_regular_today = float(regular_today['total']) if regular_today and regular_today['total'] else 0
        
        # Consulta para despesas parceladas que começam hoje
        cursor.execute('''
            SELECT SUM(amount / total_installments) as total
            FROM expenses
            WHERE user_id = %s 
              AND is_installment = TRUE
              AND DATE(date) = %s
        ''', (session['user_id'], today))
        installment_today = cursor.fetchone()
        total_installment_today = float(installment_today['total']) if installment_today and installment_today['total'] else 0
        
        # Consulta para despesas recorrentes que caem hoje
        cursor.execute('''
            SELECT SUM(amount) as total
            FROM expenses
            WHERE user_id = %s 
              AND is_recurring = TRUE
              AND DATE(date) = %s
              AND (recurring_end_date IS NULL OR recurring_end_date >= %s)
        ''', (session['user_id'], today, today))
        recurring_today = cursor.fetchone()
        total_recurring_today = float(recurring_today['total']) if recurring_today and recurring_today['total'] else 0
        
        # Calcular o total de despesas de hoje
        today_expenses = total_regular_today + total_installment_today + total_recurring_today
        
    except mysql.connector.Error as err:
        print(f"Error retrieving today's expenses: {err}")
        today_expenses = 0
    
    # Get expense categories for pie chart
    try:
        # Consulta para despesas normais (não recorrentes e não parceladas) por categoria
        cursor.execute('''
            SELECT c.name, SUM(e.amount) as total
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.id
            WHERE e.user_id = %s 
              AND MONTH(e.date) = %s 
              AND YEAR(e.date) = %s
              AND (e.is_recurring = FALSE OR e.is_recurring IS NULL)
              AND (e.is_installment = FALSE OR e.is_installment IS NULL)
            GROUP BY c.name
        ''', (session['user_id'], current_month, current_year))
        regular_expense_categories = cursor.fetchall()
        
        # Consulta para despesas parceladas por categoria
        cursor.execute('''
            SELECT c.name, SUM(e.amount / e.total_installments) as total
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.id
            WHERE e.user_id = %s 
              AND e.is_installment = TRUE
              AND e.date <= CURRENT_DATE()
              AND (e.date <= CURRENT_DATE() AND 
                   DATE_ADD(e.date, INTERVAL (e.total_installments - 1) MONTH) >= CURRENT_DATE())
            GROUP BY c.name
        ''', (session['user_id'],))
        installment_expense_categories = cursor.fetchall()
        
        # Consulta para despesas recorrentes por categoria
        cursor.execute('''
            SELECT c.name, SUM(e.amount) as total
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.id
            WHERE e.user_id = %s 
              AND e.is_recurring = TRUE
              AND (
                  -- Despesas recorrentes de meses anteriores
                  (e.date <= CURRENT_DATE() AND (e.recurring_end_date IS NULL OR e.recurring_end_date >= CURRENT_DATE()))
                  OR
                  -- Despesas recorrentes cadastradas no mês atual, mas com data futura
                  (MONTH(e.date) = %s AND YEAR(e.date) = %s AND e.date > CURRENT_DATE())
              )
              AND (
                  (e.recurring_type = 'monthly') OR
                  (e.recurring_type = 'yearly' AND MONTH(e.date) = %s) OR
                  (e.recurring_type = 'weekly')
              )
            GROUP BY c.name
        ''', (session['user_id'], current_month, current_year, current_month))
        recurring_expense_categories = cursor.fetchall()
        
        # Combinar os resultados
        expense_categories_dict = {}
        
        # Adicionar despesas normais
        for category in regular_expense_categories:
            expense_categories_dict[category['name']] = category['total']
        
        # Adicionar despesas parceladas
        for category in installment_expense_categories:
            if category['name'] in expense_categories_dict:
                expense_categories_dict[category['name']] += category['total']
            else:
                expense_categories_dict[category['name']] = category['total']
        
        # Adicionar despesas recorrentes
        for category in recurring_expense_categories:
            if category['name'] in expense_categories_dict:
                expense_categories_dict[category['name']] += category['total']
            else:
                expense_categories_dict[category['name']] = category['total']
        
        # Converter para o formato esperado pelo template
        expense_categories = [{'name': name, 'total': total} for name, total in expense_categories_dict.items()]
    except mysql.connector.Error as err:
        print(f"Error retrieving expense categories: {err}")
        expense_categories = []
    
    # Obter dados de despesas mensais para o gráfico de barras
    try:
        # Obter o ano atual
        current_year = datetime.now().year
        
        # Inicializar array com todos os meses
        monthly_expenses_data = []
        for month in range(1, 13):
            monthly_expenses_data.append({
                'month': month,
                'year': current_year,
                'total': 0
            })
        
        # Consulta para despesas normais (não recorrentes e não parceladas)
        cursor.execute('''
            SELECT SUM(amount) as total, MONTH(date) as month
            FROM expenses
            WHERE user_id = %s 
            AND YEAR(date) = %s
            AND (is_recurring = FALSE OR is_recurring IS NULL)
            AND (is_installment = FALSE OR is_installment IS NULL)
            GROUP BY MONTH(date)
        ''', (session['user_id'], current_year))
        regular_expenses = cursor.fetchall()
        
        # Adicionar despesas normais ao array
        for expense in regular_expenses:
            if 1 <= expense['month'] <= 12:
                monthly_expenses_data[expense['month']-1]['total'] += float(expense['total'] or 0)
        
        # Consulta para despesas parceladas - obter detalhes de cada despesa parcelada
        cursor.execute('''
            SELECT id, description, amount, date, total_installments
            FROM expenses
            WHERE user_id = %s 
            AND is_installment = TRUE
            AND (YEAR(date) = %s OR YEAR(DATE_ADD(date, INTERVAL (total_installments - 1) MONTH)) = %s)
        ''', (session['user_id'], current_year, current_year))
        installment_details = cursor.fetchall()
        
        # Debug para verificar as despesas parceladas
        print("Detalhes das despesas parceladas:")
        for expense in installment_details:
            print(f"ID: {expense['id']}, Descrição: {expense['description']}, Valor: {expense['amount']}, "
                  f"Data: {expense['date']}, Parcelas: {expense['total_installments']}")
        
        # Distribuir as parcelas pelos meses corretos
        for expense in installment_details:
            start_date = expense['date']
            total_installments = expense['total_installments']
            installment_value = expense['amount'] / total_installments
            
            # Para cada parcela, adicionar ao mês correspondente
            for i in range(total_installments):
                # Calcular a data da parcela atual (usando mês real, não aproximação)
                month_offset = i
                installment_year = start_date.year + ((start_date.month - 1 + month_offset) // 12)
                installment_month = ((start_date.month - 1 + month_offset) % 12) + 1
                installment_date = datetime(installment_year, installment_month, min(start_date.day, 28)).date()
                
                # Se a parcela for para o ano atual, adicionar ao array
                if installment_year == current_year and 1 <= installment_month <= 12:
                    monthly_expenses_data[installment_month-1]['total'] += float(installment_value)
                    print(f"Adicionando parcela {i+1}/{total_installments} de {expense['description']} "
                          f"no mês {installment_month}/{installment_year}: R$ {installment_value:.2f}")

        
        # O processamento das despesas parceladas já foi feito acima
        
        # Consulta para despesas recorrentes mensais
        cursor.execute('''
            SELECT 
                MONTH(DATE_ADD(date, INTERVAL n MONTH)) as month,
                SUM(amount) as total
            FROM 
                expenses,
                (SELECT 0 as n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION
                 SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION
                 SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11) as numbers
            WHERE 
                user_id = %s 
                AND is_recurring = TRUE
                AND recurring_type = 'monthly'
                AND YEAR(DATE_ADD(date, INTERVAL n MONTH)) = %s
                -- Não filtra mais por data <= CURRENT_DATE() para incluir despesas futuras do mês atual
                AND (recurring_end_date IS NULL OR DATE_ADD(date, INTERVAL n MONTH) <= recurring_end_date)
            GROUP BY 
                MONTH(DATE_ADD(date, INTERVAL n MONTH))
        ''', (session['user_id'], current_year))
        recurring_monthly_expenses = cursor.fetchall()
        
        # Adicionar despesas recorrentes mensais ao array
        for expense in recurring_monthly_expenses:
            if 1 <= expense['month'] <= 12:
                monthly_expenses_data[expense['month']-1]['total'] += float(expense['total'] or 0)
        
        # Consulta para despesas recorrentes anuais
        cursor.execute('''
            SELECT 
                MONTH(date) as month,
                SUM(amount) as total
            FROM 
                expenses
            WHERE 
                user_id = %s 
                AND is_recurring = TRUE
                AND recurring_type = 'yearly'
                AND (recurring_end_date IS NULL OR %s <= YEAR(recurring_end_date))
            GROUP BY 
                MONTH(date)
        ''', (session['user_id'], current_year))
        recurring_yearly_expenses = cursor.fetchall()
        
        # Adicionar despesas recorrentes anuais ao array
        for expense in recurring_yearly_expenses:
            if 1 <= expense['month'] <= 12:
                monthly_expenses_data[expense['month']-1]['total'] += float(expense['total'] or 0)
        
    except mysql.connector.Error as err:
        print(f"Error retrieving monthly expenses data: {err}")
        monthly_expenses_data = []
    
    # Obter dados de receitas mensais para o gráfico de barras
    try:
        # Inicializar array com todos os meses
        monthly_income_data = []
        for month in range(1, 13):
            monthly_income_data.append({
                'month': month,
                'year': current_year,
                'total': 0
            })
        
        # Consulta para receitas
        cursor.execute('''
            SELECT SUM(amount) as total, MONTH(date) as month
            FROM income
            WHERE user_id = %s AND YEAR(date) = %s
            GROUP BY MONTH(date)
        ''', (session['user_id'], current_year))
        income_data = cursor.fetchall()
        
        # Adicionar receitas ao array
        for income in income_data:
            if 1 <= income['month'] <= 12:
                monthly_income_data[income['month']-1]['total'] += float(income['total'] or 0)
        
    except mysql.connector.Error as err:
        print(f"Error retrieving monthly income data: {err}")
        monthly_income_data = []
    
    cursor.close()
    conn.close()
    
    return render_template('dashboard.html', 
                           recent_expenses=recent_expenses,
                           recent_investments=recent_investments,
                           monthly_expenses=monthly_expenses,
                           monthly_income=monthly_income,
                           expense_categories=expense_categories,
                           total_investments=total_investments,
                           monthly_expenses_data=monthly_expenses_data,
                           monthly_income_data=monthly_income_data,
                           today_expenses=today_expenses,
                           total_expenses_value=total_expenses_value)

# Import and register blueprints
from routes import expenses_bp, investments_bp, income_bp, budgets_bp, categories_bp
from reports import reports_bp

# Register blueprints
app.register_blueprint(expenses_bp)
app.register_blueprint(investments_bp)
app.register_blueprint(income_bp)
app.register_blueprint(budgets_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(reports_bp)

# Função para iniciar o servidor Flask em uma thread separada
def start_flask_server(log_text):
    # Configurar o logger do Flask para usar nosso handler personalizado
    handler = TkinterLogHandler(log_text)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    # Configurar o logger do Flask e Werkzeug
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    logging.getLogger('werkzeug').addHandler(handler)
    logging.getLogger('werkzeug').setLevel(logging.INFO)
    
    # Desativar o logger padrão do Werkzeug
    log = logging.getLogger('werkzeug')
    log.disabled = False
    
    # Iniciar o servidor Flask
    try:
        # Desabilitar reloader e debug para evitar problemas com threading
        app.run(debug=False, port=4332, use_reloader=False)
    except Exception as e:
        app.logger.error(f"Erro ao iniciar o servidor Flask: {e}")

# Função para criar e iniciar a interface TTK
def create_ttk_interface():
    root = tk.Tk()
    root.title("Gerenciador de Gastos - Logs do Servidor")
    root.geometry("800x600")

    # Configurar estilo
    style = ttk.Style()
    style.theme_use('clam')  # Usar um tema moderno

    # Frame principal
    main_frame = ttk.Frame(root, padding="10")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # Label de título
    title_label = ttk.Label(main_frame, text="Logs do Servidor", font=("Helvetica", 14, "bold"))
    title_label.pack(pady=10)

    # Frame para o widget de texto com scrollbar
    text_frame = ttk.Frame(main_frame)
    text_frame.pack(fill=tk.BOTH, expand=True)

    # Scrollbar
    scrollbar = ttk.Scrollbar(text_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Widget de texto para os logs
    log_text = tk.Text(text_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set)
    log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=log_text.yview)

    # Configurar cores
    log_text.config(bg="#f0f0f0", fg="#333333")

    # Botão para limpar logs
    clear_button = ttk.Button(main_frame, text="Limpar Logs", command=lambda: log_text.delete(1.0, tk.END))
    clear_button.pack(pady=10)
    
    # Botão para abrir o navegador
    def open_browser():
        import webbrowser
        webbrowser.open('http://localhost:4332')
    
    browser_button = ttk.Button(main_frame, text="Abrir no Navegador", command=open_browser)
    browser_button.pack(pady=5)

    # Mensagem inicial
    log_text.insert(tk.END, "=== Servidor Gerenciador de Gastos ===\n")
    log_text.insert(tk.END, f"Iniciado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
    log_text.insert(tk.END, "Aguardando conexões na porta 4332...\n\n")
    
    # Configurar o log_text como readonly após a mensagem inicial
    log_text.configure(state='disabled')

    # Iniciar o servidor Flask em uma thread separada
    flask_thread = threading.Thread(target=start_flask_server, args=(log_text,))
    flask_thread.daemon = True  # Thread será encerrada quando o programa principal terminar
    flask_thread.start()

    # Função para fechar a aplicação
    def on_closing():
        root.destroy()
        os._exit(0)  # Força o encerramento de todas as threads
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    # Iniciar o loop principal do Tkinter
    root.mainloop()

# Run the application
if __name__ == '__main__':
    create_ttk_interface()
