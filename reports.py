from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
import mysql.connector
import json
import requests
import os
import pandas as pd
import io
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from decimal import Decimal
from routes import get_db_connection, login_required

# Custom JSON encoder to handle Decimal objects
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif hasattr(obj, 'isoformat'):
            # This will handle date, datetime and time objects
            return obj.isoformat()
        return super(DecimalEncoder, self).default(obj)

# Create blueprint for reports
reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports')
@login_required
def reports_list():
    """Render the reports page with month/year selection form"""
    # Get current month and year for default values
    now = datetime.now()
    current_month = now.month
    current_year = now.year
    
    # Create a list of months for the dropdown
    months = [
        {"value": 1, "name": "Janeiro"},
        {"value": 2, "name": "Fevereiro"},
        {"value": 3, "name": "Março"},
        {"value": 4, "name": "Abril"},
        {"value": 5, "name": "Maio"},
        {"value": 6, "name": "Junho"},
        {"value": 7, "name": "Julho"},
        {"value": 8, "name": "Agosto"},
        {"value": 9, "name": "Setembro"},
        {"value": 10, "name": "Outubro"},
        {"value": 11, "name": "Novembro"},
        {"value": 12, "name": "Dezembro"}
    ]
    
    # Create a list of years (current year and 5 years back)
    years = list(range(current_year - 5, current_year + 1))
    
    return render_template('reports/list.html', 
                          months=months, 
                          years=years, 
                          current_month=current_month, 
                          current_year=current_year)

@reports_bp.route('/reports/generate', methods=['POST'])
@login_required
def generate_report():
    """Generate a financial report for the selected month and year using AI"""
    month = int(request.form.get('month', datetime.now().month))
    year = int(request.form.get('year', datetime.now().year))
    
    # Get financial data for the selected month and year
    financial_data = get_financial_data(month, year)
    
    # Generate AI analysis
    ai_analysis = get_ai_analysis(financial_data, month, year)
    
    # Return the report data
    return render_template('reports/view.html', 
                          report=ai_analysis,
                          month=month,
                          year=year,
                          month_name=get_month_name(month),
                          charts=financial_data.get('charts', {}))

def get_month_name(month_number):
    """Convert month number to month name in Portuguese"""
    months = {
        1: "Janeiro",
        2: "Fevereiro",
        3: "Março",
        4: "Abril",
        5: "Maio",
        6: "Junho",
        7: "Julho",
        8: "Agosto",
        9: "Setembro",
        10: "Outubro",
        11: "Novembro",
        12: "Dezembro"
    }
    return months.get(month_number, "")

def get_financial_data(month, year):
    """Collect all financial data for the selected month and year"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    user_id = session['user_id']
    
    # Dictionary to store all financial data
    financial_data = {
        "expenses": {
            "total": 0,
            "by_category": [],
            "recurring": [],
            "installments": []
        },
        "income": {
            "total": 0,
            "by_source": []
        },
        "investments": {
            "total": 0,
            "by_type": []
        },
        "budgets": [],
        "charts": {}
    }
    
    # Get expenses data
    # Regular expenses
    cursor.execute('''
        SELECT 
            e.*, c.name as category_name 
        FROM 
            expenses e 
        JOIN 
            expense_categories c ON e.category_id = c.id 
        WHERE 
            e.user_id = %s 
            AND MONTH(e.date) = %s 
            AND YEAR(e.date) = %s
            AND e.is_recurring = FALSE
            AND e.is_installment = FALSE
        ORDER BY 
            e.date DESC
    ''', (user_id, month, year))
    regular_expenses = cursor.fetchall()
    
    # Recurring monthly expenses
    cursor.execute('''
        SELECT 
            e.*, c.name as category_name 
        FROM 
            expenses e 
        JOIN 
            expense_categories c ON e.category_id = c.id 
        WHERE 
            e.user_id = %s 
            AND e.is_recurring = TRUE
            AND e.recurring_type = 'monthly'
            AND (
                (MONTH(e.date) <= %s AND YEAR(e.date) <= %s)
                AND (e.recurring_end_date IS NULL OR 
                    (YEAR(e.recurring_end_date) >= %s AND 
                    (YEAR(e.recurring_end_date) > %s OR MONTH(e.recurring_end_date) >= %s)))
            )
        ORDER BY 
            e.date DESC
    ''', (user_id, month, year, year, year, month))
    recurring_monthly_expenses = cursor.fetchall()
    
    # Recurring yearly expenses
    cursor.execute('''
        SELECT 
            e.*, c.name as category_name 
        FROM 
            expenses e 
        JOIN 
            expense_categories c ON e.category_id = c.id 
        WHERE 
            e.user_id = %s 
            AND e.is_recurring = TRUE
            AND e.recurring_type = 'yearly'
            AND MONTH(e.date) = %s
            AND (
                YEAR(e.date) <= %s
                AND (e.recurring_end_date IS NULL OR YEAR(e.recurring_end_date) >= %s)
            )
        ORDER BY 
            e.date DESC
    ''', (user_id, month, year, year))
    recurring_yearly_expenses = cursor.fetchall()
    
    # Installment expenses
    cursor.execute('''
        SELECT 
            e.*, c.name as category_name 
        FROM 
            expenses e 
        JOIN 
            expense_categories c ON e.category_id = c.id 
        WHERE 
            e.user_id = %s 
            AND e.is_installment = TRUE
            AND (
                (YEAR(e.date) < %s OR (YEAR(e.date) = %s AND MONTH(e.date) <= %s))
                AND (
                    (YEAR(e.date) = %s AND MONTH(e.date) + e.total_installments - 1 >= %s)
                    OR (YEAR(e.date) < %s AND MOD(MONTH(e.date) + e.total_installments - 1, 12) >= MOD(%s - 1, 12))
                    OR (YEAR(e.date) < %s AND MOD(MONTH(e.date) + e.total_installments - 1, 12) < MOD(MONTH(e.date) - 1, 12))
                )
            )
        ORDER BY 
            e.date DESC
    ''', (user_id, year, year, month, year, month, year, month, year))
    installment_expenses = cursor.fetchall()
    
    # Calculate total expenses
    total_expenses = 0
    for expense in regular_expenses:
        total_expenses += float(expense['amount'])
    
    for expense in recurring_monthly_expenses:
        total_expenses += float(expense['amount'])
    
    for expense in recurring_yearly_expenses:
        total_expenses += float(expense['amount'])
    
    for expense in installment_expenses:
        # Calculate which installment we're on for this month/year
        expense_date = expense['date']
        expense_month = expense_date.month
        expense_year = expense_date.year
        
        months_diff = (year - expense_year) * 12 + (month - expense_month)
        
        # Only include if this month/year falls within the installment period
        if 0 <= months_diff < expense['total_installments']:
            installment_amount = float(expense['amount']) / expense['total_installments']
            total_expenses += installment_amount
    
    financial_data['expenses']['total'] = total_expenses
    
    # Get expenses by category
    cursor.execute('''
        SELECT 
            c.name, SUM(e.amount) as total
        FROM 
            expenses e
        JOIN 
            expense_categories c ON e.category_id = c.id
        WHERE 
            e.user_id = %s 
            AND MONTH(e.date) = %s 
            AND YEAR(e.date) = %s
            AND e.is_recurring = FALSE
            AND e.is_installment = FALSE
        GROUP BY 
            c.name
    ''', (user_id, month, year))
    expenses_by_category = cursor.fetchall()
    
    # Add recurring and installment expenses to categories
    category_totals = {}
    for category in expenses_by_category:
        category_totals[category['name']] = float(category['total'])
    
    # Add recurring monthly expenses to categories
    for expense in recurring_monthly_expenses:
        category_name = expense['category_name']
        if category_name in category_totals:
            category_totals[category_name] += float(expense['amount'])
        else:
            category_totals[category_name] = float(expense['amount'])
    
    # Add recurring yearly expenses to categories
    for expense in recurring_yearly_expenses:
        category_name = expense['category_name']
        if category_name in category_totals:
            category_totals[category_name] += float(expense['amount'])
        else:
            category_totals[category_name] = float(expense['amount'])
    
    # Add installment expenses to categories
    for expense in installment_expenses:
        expense_date = expense['date']
        expense_month = expense_date.month
        expense_year = expense_date.year
        
        months_diff = (year - expense_year) * 12 + (month - expense_month)
        
        if 0 <= months_diff < expense['total_installments']:
            installment_amount = float(expense['amount']) / expense['total_installments']
            category_name = expense['category_name']
            
            if category_name in category_totals:
                category_totals[category_name] += installment_amount
            else:
                category_totals[category_name] = installment_amount
    
    # Convert to list format
    financial_data['expenses']['by_category'] = [
        {"name": name, "total": total} for name, total in category_totals.items()
    ]
    
    # Get income data
    cursor.execute('''
        SELECT 
            i.*, s.name as source_name 
        FROM 
            income i 
        JOIN 
            income_sources s ON i.source_id = s.id 
        WHERE 
            i.user_id = %s 
            AND MONTH(i.date) = %s 
            AND YEAR(i.date) = %s
        ORDER BY 
            i.date DESC
    ''', (user_id, month, year))
    income_data = cursor.fetchall()
    
    # Calculate total income
    total_income = sum(float(income['amount']) for income in income_data)
    financial_data['income']['total'] = total_income
    
    # Get income by source
    cursor.execute('''
        SELECT 
            s.name, SUM(i.amount) as total
        FROM 
            income i
        JOIN 
            income_sources s ON i.source_id = s.id
        WHERE 
            i.user_id = %s 
            AND MONTH(i.date) = %s 
            AND YEAR(i.date) = %s
        GROUP BY 
            s.name
    ''', (user_id, month, year))
    income_by_source = cursor.fetchall()
    financial_data['income']['by_source'] = income_by_source
    
    # Get investments data
    cursor.execute('''
        SELECT 
            i.*, t.name as type_name 
        FROM 
            investments i 
        JOIN 
            investment_types t ON i.type_id = t.id 
        WHERE 
            i.user_id = %s 
            AND MONTH(i.date) = %s 
            AND YEAR(i.date) = %s
        ORDER BY 
            i.date DESC
    ''', (user_id, month, year))
    investments_data = cursor.fetchall()
    
    # Calculate total investments
    total_investments = sum(float(investment['amount']) for investment in investments_data)
    financial_data['investments']['total'] = total_investments
    
    # Get investments by type
    cursor.execute('''
        SELECT 
            t.name, SUM(i.amount) as total
        FROM 
            investments i
        JOIN 
            investment_types t ON i.type_id = t.id
        WHERE 
            i.user_id = %s 
            AND MONTH(i.date) = %s 
            AND YEAR(i.date) = %s
        GROUP BY 
            t.name
    ''', (user_id, month, year))
    investments_by_type = cursor.fetchall()
    financial_data['investments']['by_type'] = investments_by_type
    
    # Get budgets data
    # Create a date for the first day of the selected month/year
    target_date = f'{year}-{month:02d}-01'
    
    cursor.execute('''
        SELECT 
            b.*, c.name as category_name 
        FROM 
            budgets b 
        JOIN 
            expense_categories c ON b.category_id = c.id 
        WHERE 
            b.user_id = %s 
            AND %s BETWEEN b.start_date AND b.end_date
        ORDER BY 
            b.amount DESC
    ''', (user_id, target_date))
    budgets_data = cursor.fetchall()
    financial_data['budgets'] = budgets_data
    
    # Generate charts
    financial_data['charts'] = generate_charts(financial_data)
    
    cursor.close()
    conn.close()
    
    return financial_data

def generate_charts(financial_data):
    """Generate charts for the financial report"""
    charts = {}
    
    # Expenses by category pie chart
    if financial_data['expenses']['by_category']:
        plt.figure(figsize=(10, 6))
        labels = [item['name'] for item in financial_data['expenses']['by_category']]
        values = [float(item['total']) for item in financial_data['expenses']['by_category']]
        
        # Sort by value descending
        sorted_data = sorted(zip(labels, values), key=lambda x: x[1], reverse=True)
        
        # If there are more than 7 categories, group the smallest ones as "Others"
        if len(sorted_data) > 7:
            top_categories = sorted_data[:6]
            others_sum = sum(value for _, value in sorted_data[6:])
            
            labels = [label for label, _ in top_categories] + ["Outros"]
            values = [value for _, value in top_categories] + [others_sum]
        else:
            labels = [label for label, _ in sorted_data]
            values = [value for _, value in sorted_data]
        
        plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
        plt.axis('equal')
        plt.title('Despesas por Categoria')
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        charts['expenses_by_category'] = base64.b64encode(buffer.getvalue()).decode('utf-8')
        plt.close()
    
    # Income vs Expenses vs Investments bar chart
    plt.figure(figsize=(10, 6))
    categories = ['Receitas', 'Despesas', 'Investimentos']
    values = [
        financial_data['income']['total'],
        financial_data['expenses']['total'],
        financial_data['investments']['total']
    ]
    
    plt.bar(categories, values, color=['green', 'red', 'blue'])
    plt.title('Receitas vs Despesas vs Investimentos')
    plt.ylabel('Valor (R$)')
    
    # Add values on top of bars
    for i, v in enumerate(values):
        plt.text(i, v + 50, f'R$ {v:.2f}', ha='center')
    
    # Save to base64
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    charts['income_vs_expenses'] = base64.b64encode(buffer.getvalue()).decode('utf-8')
    plt.close()
    
    # Investments by type pie chart
    if financial_data['investments']['by_type']:
        plt.figure(figsize=(10, 6))
        labels = [item['name'] for item in financial_data['investments']['by_type']]
        values = [float(item['total']) for item in financial_data['investments']['by_type']]
        
        plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
        plt.axis('equal')
        plt.title('Investimentos por Tipo')
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        charts['investments_by_type'] = base64.b64encode(buffer.getvalue()).decode('utf-8')
        plt.close()
    
    # Budget vs Actual expenses
    if financial_data['budgets']:
        # Create a dictionary of budgets by category
        budget_by_category = {budget['category_name']: float(budget['amount']) for budget in financial_data['budgets']}
        
        # Create a dictionary of actual expenses by category
        actual_by_category = {item['name']: float(item['total']) for item in financial_data['expenses']['by_category']}
        
        # Get all unique categories
        all_categories = set(list(budget_by_category.keys()) + list(actual_by_category.keys()))
        
        # Create lists for the chart
        categories = []
        budget_values = []
        actual_values = []
        
        for category in all_categories:
            categories.append(category)
            budget_values.append(budget_by_category.get(category, 0))
            actual_values.append(actual_by_category.get(category, 0))
        
        # Sort by budget value
        sorted_data = sorted(zip(categories, budget_values, actual_values), key=lambda x: x[1], reverse=True)
        
        # If there are more than 7 categories, only show the top 7
        if len(sorted_data) > 7:
            sorted_data = sorted_data[:7]
        
        # Unzip the sorted data
        categories = [item[0] for item in sorted_data]
        budget_values = [item[1] for item in sorted_data]
        actual_values = [item[2] for item in sorted_data]
        
        # Create the chart
        plt.figure(figsize=(12, 6))
        x = range(len(categories))
        width = 0.35
        
        plt.bar([i - width/2 for i in x], budget_values, width, label='Orçamento')
        plt.bar([i + width/2 for i in x], actual_values, width, label='Real')
        
        plt.xlabel('Categoria')
        plt.ylabel('Valor (R$)')
        plt.title('Orçamento vs Despesas Reais')
        plt.xticks(x, categories, rotation=45, ha='right')
        plt.legend()
        plt.tight_layout()
        
        # Save to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        charts['budget_vs_actual'] = base64.b64encode(buffer.getvalue()).decode('utf-8')
        plt.close()
    
    return charts

def get_ai_analysis(financial_data, month, year):
    """Generate AI analysis of the financial data using OpenRouter API"""
    # Format the data for the AI
    month_name = get_month_name(month)
    
    # Prepare the prompt
    prompt = f"""
    Analise os seguintes dados financeiros para o mês de {month_name} de {year} e forneça insights úteis e recomendações para melhorar a saúde financeira:
    
    RECEITAS:
    Total: R$ {financial_data['income']['total']:.2f}
    Detalhamento por fonte:
    {json.dumps([dict(item) for item in financial_data['income']['by_source']], indent=2, cls=DecimalEncoder)}
    
    DESPESAS:
    Total: R$ {financial_data['expenses']['total']:.2f}
    Detalhamento por categoria:
    {json.dumps([dict(item) for item in financial_data['expenses']['by_category']], indent=2, cls=DecimalEncoder)}
    
    INVESTIMENTOS:
    Total: R$ {financial_data['investments']['total']:.2f}
    Detalhamento por tipo:
    {json.dumps([dict(item) for item in financial_data['investments']['by_type']], indent=2, cls=DecimalEncoder)}
    
    ORÇAMENTOS:
    {json.dumps([dict(item) for item in financial_data['budgets']], indent=2, cls=DecimalEncoder)}
    
    Por favor, analise esses dados e forneça:
    1. Um resumo geral da situação financeira do mês
    2. Análise detalhada de despesas, identificando categorias com gastos elevados
    3. Análise da relação entre receitas e despesas
    4. Análise dos investimentos e sua distribuição
    5. Comparação entre orçamentos planejados e gastos reais
    6. Recomendações específicas para melhorar a saúde financeira
    7. Sugestões de metas para o próximo mês
    
    Formate sua resposta em HTML com seções bem definidas, usando tags <h2>, <h3>, <p>, <ul>, <li>, etc.
    """
    
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise RuntimeError("Environment variable OPENROUTER_API_KEY not set")
    model = os.getenv('OPENROUTER_MODEL', "meta-llama/llama-4-scout:free")

    try:
        # Make the API call to OpenRouter with a timeout of 120 seconds (2 minutes)
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://financialmanager.app",
                "X-Title": "Financial Manager App",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                # Add a max_tokens parameter to limit response size for large datasets
                "max_tokens": 2000
            },
            timeout=120  # Set a timeout of 120 seconds
        )
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            ai_analysis = result['choices'][0]['message']['content']
            return ai_analysis
        else:
            # If there was an error, return a message
            error_message = f"""
            <h2>Erro na Análise</h2>
            <p>Não foi possível gerar a análise financeira. Erro: {response.status_code}</p>
            <p>Detalhes: {response.text}</p>
            <p>Tente novamente ou selecione um mês com menos dados.</p>
            """
            return error_message
            
    except requests.exceptions.Timeout:
        # Handle timeout specifically
        error_message = f"""
        <h2>Tempo Esgotado na Análise</h2>
        <p>A análise financeira demorou muito tempo para ser concluída. Isso geralmente acontece quando há muitos dados para processar.</p>
        <p>Sugestões:</p>
        <ul>
            <li>Tente novamente mais tarde quando o servidor estiver menos ocupado</li>
            <li>Selecione um mês com menos transações</li>
        </ul>
        """
        return error_message
    except Exception as e:
        # If there was an exception, return a message
        error_message = f"""
        <h2>Erro na Análise</h2>
        <p>Não foi possível gerar a análise financeira. Erro: {str(e)}</p>
        <p>Tente novamente ou selecione um mês com menos dados.</p>
        """
        return error_message

# Blueprint URL
reports_bp.url_prefix = '/reports'
