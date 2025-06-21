from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import mysql.connector
import dbcreate
from functools import wraps
import pandas as pd
import os
import tempfile
import io
# Currency scraper import removed

# Database connection function
def get_db_connection():
    connection = mysql.connector.connect(
        host=dbcreate.DB_HOST,
        port=dbcreate.DB_PORT,
        user=dbcreate.DB_USER,
        password=dbcreate.DB_PASSWORD,
        database=dbcreate.DB_NAME
    )
    return connection

# Authentication middleware
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, faça login para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped_view

# Create blueprints for different sections
expenses_bp = Blueprint('expenses', __name__)
investments_bp = Blueprint('investments', __name__)
income_bp = Blueprint('income', __name__)
budgets_bp = Blueprint('budgets', __name__)
categories_bp = Blueprint('categories', __name__)
# Currency blueprint removed

# Expenses routes
@expenses_bp.route('/expenses')
@login_required
def expenses_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Preparar filtros
    filters = ["e.user_id = %s"]
    params = [session['user_id']]
    
    # Filtro por categoria
    category_id = request.args.get('category_id')
    if category_id and category_id.isdigit() and int(category_id) > 0:
        filters.append("e.category_id = %s")
        params.append(int(category_id))
    
    # Filtro por tipo de despesa
    expense_type = request.args.get('expense_type')
    if expense_type == 'recurring':
        filters.append("e.is_recurring = TRUE")
    elif expense_type == 'installment':
        filters.append("e.is_installment = TRUE")
    elif expense_type == 'single':
        filters.append("(e.is_recurring = FALSE AND e.is_installment = FALSE)")
    
    # Filtro por data
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Validar que a data final não é menor que a data inicial
    if start_date and end_date and end_date < start_date:
        flash('A data final não pode ser menor que a data inicial.', 'danger')
        # Redefine a data final para ser igual à data inicial
        end_date = start_date
    
    if start_date:
        filters.append("e.date >= %s")
        params.append(start_date)
    
    if end_date:
        filters.append("e.date <= %s")
        params.append(end_date)
    
    # Construir a consulta SQL com os filtros
    query = f'''
        SELECT e.*, c.name as category_name 
        FROM expenses e 
        JOIN expense_categories c ON e.category_id = c.id 
        WHERE {' AND '.join(filters)} 
        ORDER BY e.date DESC
    '''
    
    try:
        cursor.execute(query, tuple(params))
        expenses = cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error retrieving expenses: {err}")
        expenses = []
    
    # Get expense categories for the form (both system defaults and user-specific)
    try:
        cursor.execute(
            'SELECT * FROM expense_categories WHERE user_id IS NULL OR user_id = %s ORDER BY name', 
            (session['user_id'],)
        )
        categories = cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error retrieving expense categories: {err}")
        categories = []
    
    cursor.close()
    conn.close()
    
    return render_template('expenses/list.html', expenses=expenses, categories=categories)

@expenses_bp.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        category_id = request.form['category_id']
        amount = request.form['amount']
        description = request.form['description']
        date = request.form['date']
        expense_type = request.form.get('expense_type', 'single')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Processar de acordo com o tipo de despesa
        if expense_type == 'single':
            # Despesa única (normal)
            cursor.execute(
                'INSERT INTO expenses (user_id, category_id, amount, description, date) VALUES (%s, %s, %s, %s, %s)',
                (session['user_id'], category_id, amount, description, date)
            )
            conn.commit()
            flash('Despesa adicionada com sucesso!', 'success')
            
        elif expense_type == 'recurring':
            # Despesa recorrente
            recurring_type = request.form['recurring_type']
            recurring_end_date = request.form.get('recurring_end_date')
            
            # Verificar se a data final da recorrência foi fornecida
            if not recurring_end_date:
                # Se não foi fornecida, definir como NULL (sem data final)
                recurring_end_date = None
            
            # Validar que a data final de recorrência não é menor que a data inicial
            if recurring_end_date and date and recurring_end_date < date:
                flash('A data final de recorrência não pode ser menor que a data inicial.', 'danger')
                
                # Get expense categories for the form
                cursor.execute('SELECT * FROM expense_categories ORDER BY name')
                categories = cursor.fetchall()
                
                cursor.close()
                conn.close()
                
                return render_template('expenses/add.html', categories=categories)
            
            # Inserir a despesa recorrente como um único registro
            cursor.execute(
                '''INSERT INTO expenses 
                   (user_id, category_id, amount, description, date, is_recurring, recurring_type, recurring_end_date) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (session['user_id'], category_id, amount, description, date, True, recurring_type, recurring_end_date)
            )
            conn.commit()
            
            flash('Despesa recorrente adicionada com sucesso!', 'success')
            
        elif expense_type == 'installment':
            # Despesa parcelada
            total_installments = int(request.form['total_installments'])
            
            if total_installments <= 0:
                flash('O número de parcelas deve ser maior que zero.', 'danger')
                return redirect(url_for('expenses.add_expense'))
            
            # Calcular o valor de cada parcela (arredondando para 2 casas decimais)
            installment_amount = round(float(amount) / total_installments, 2)
            
            # Obter a data da primeira parcela
            start_date = datetime.strptime(date, '%Y-%m-%d')
            
            # Inserir apenas um registro para a despesa parcelada
            cursor.execute(
                '''INSERT INTO expenses 
                   (user_id, category_id, amount, description, date, is_installment, total_installments, installment_number) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (session['user_id'], category_id, amount, description, 
                 date, True, total_installments, 1)
            )
            conn.commit()
            
            flash(f'Despesa parcelada adicionada com sucesso! Será contabilizada em {total_installments} parcelas.', 'success')
        
        cursor.close()
        conn.close()
        
        return redirect(url_for('expenses.expenses_list'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get expense categories for the form
    cursor.execute('SELECT * FROM expense_categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('expenses/add.html', categories=categories)

@expenses_bp.route('/expenses/delete/<int:id>', methods=['GET'])
@login_required
def delete_expense(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Verificar se a despesa existe e pertence ao usuário
    cursor.execute('SELECT * FROM expenses WHERE id = %s AND user_id = %s', (id, session['user_id']))
    expense = cursor.fetchone()
    
    if not expense:
        flash('Despesa não encontrada.', 'danger')
        return redirect(url_for('expenses.expenses_list'))
    
    # Excluir a despesa
    cursor.execute('DELETE FROM expenses WHERE id = %s', (id,))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    if expense['is_recurring']:
        flash('Despesa recorrente excluída com sucesso!', 'success')
    elif expense['is_installment']:
        flash('Despesa parcelada excluída com sucesso!', 'success')
    else:
        flash('Despesa excluída com sucesso!', 'success')
    
    return redirect(url_for('expenses.expenses_list'))

@expenses_bp.route('/expenses/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_expense(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        category_id = request.form['category_id']
        amount = request.form['amount']
        description = request.form['description']
        date = request.form['date']
        
        # Get the expense to check its type
        cursor.execute('SELECT * FROM expenses WHERE id = %s AND user_id = %s', (id, session['user_id']))
        expense = cursor.fetchone()
        
        if not expense:
            flash('Despesa não encontrada.', 'danger')
            return redirect(url_for('expenses.expenses_list'))
        
        # Processar de acordo com o tipo de despesa
        if expense['is_installment']:
            # Despesa parcelada - atualizar número de parcelas se fornecido
            total_installments = request.form.get('total_installments')
            
            if total_installments and int(total_installments) > 0:
                cursor.execute(
                    'UPDATE expenses SET category_id = %s, amount = %s, description = %s, date = %s, total_installments = %s WHERE id = %s AND user_id = %s',
                    (category_id, amount, description, date, total_installments, id, session['user_id'])
                )
            else:
                cursor.execute(
                    'UPDATE expenses SET category_id = %s, amount = %s, description = %s, date = %s WHERE id = %s AND user_id = %s',
                    (category_id, amount, description, date, id, session['user_id'])
                )
        
        elif expense['is_recurring']:
            # Despesa recorrente - atualizar tipo de recorrência e data final se fornecidos
            recurring_type = request.form.get('recurring_type')
            recurring_end_date = request.form.get('recurring_end_date')
            
            # Verificar se a data final da recorrência foi fornecida
            if not recurring_end_date or recurring_end_date.strip() == '':
                # Se não foi fornecida, definir como NULL (sem data final)
                recurring_end_date = None
            
            # Validar que a data final de recorrência não é menor que a data inicial
            if recurring_end_date and date and recurring_end_date < date:
                flash('A data final de recorrência não pode ser menor que a data inicial.', 'danger')
                
                # Get expense categories for the form
                cursor.execute('SELECT * FROM expense_categories ORDER BY name')
                categories = cursor.fetchall()
                
                return render_template('expenses/edit.html', expense=expense, categories=categories)
            
            cursor.execute(
                'UPDATE expenses SET category_id = %s, amount = %s, description = %s, date = %s, recurring_type = %s, recurring_end_date = %s WHERE id = %s AND user_id = %s',
                (category_id, amount, description, date, recurring_type, recurring_end_date, id, session['user_id'])
            )
        
        else:
            # Despesa única (normal)
            cursor.execute(
                'UPDATE expenses SET category_id = %s, amount = %s, description = %s, date = %s WHERE id = %s AND user_id = %s',
                (category_id, amount, description, date, id, session['user_id'])
            )
        
        conn.commit()
        
        flash('Despesa atualizada com sucesso!', 'success')
        return redirect(url_for('expenses.expenses_list'))
    
    # Get the expense
    cursor.execute('SELECT * FROM expenses WHERE id = %s AND user_id = %s', (id, session['user_id']))
    expense = cursor.fetchone()
    
    if not expense:
        flash('Despesa não encontrada.', 'danger')
        return redirect(url_for('expenses.expenses_list'))
    
    # Get expense categories for the form
    cursor.execute('SELECT * FROM expense_categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('expenses/edit.html', expense=expense, categories=categories)

# Export expenses route
@expenses_bp.route('/export', methods=['POST'])
@login_required
def export_expenses():
    expense_type = request.form.get('expense_type', 'single')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Define the query based on expense type
    if expense_type == 'single':
        query = '''
            SELECT e.date, c.name as category, e.description, e.amount
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.id
            WHERE e.user_id = %s AND e.is_recurring = FALSE AND e.is_installment = FALSE
            ORDER BY e.date DESC
        '''
        filename = 'despesas_unicas.xlsx'
        sheet_name = 'Despesas Únicas'
        
    elif expense_type == 'recurring':
        query = '''
            SELECT e.date, c.name as category, e.description, e.amount, 
                   e.recurring_type, e.recurring_end_date
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.id
            WHERE e.user_id = %s AND e.is_recurring = TRUE
            ORDER BY e.date DESC
        '''
        filename = 'despesas_recorrentes.xlsx'
        sheet_name = 'Despesas Recorrentes'
        
    elif expense_type == 'installment':
        query = '''
            SELECT e.date, c.name as category, e.description, e.amount, 
                   e.installment_number, e.total_installments
            FROM expenses e
            JOIN expense_categories c ON e.category_id = c.id
            WHERE e.user_id = %s AND e.is_installment = TRUE AND e.parent_expense_id IS NULL
            ORDER BY e.date DESC
        '''
        filename = 'despesas_parceladas.xlsx'
        sheet_name = 'Despesas Parceladas'
    
    try:
        # Obter categorias para o template
        cursor.execute('SELECT name FROM expense_categories ORDER BY name')
        categories = [category['name'] for category in cursor.fetchall()]
        
        # Criar template com uma linha vazia para preenchimento
        if expense_type == 'single':
            # Criar DataFrame com uma linha vazia para despesa única
            df = pd.DataFrame({
                'Data': [''],
                'Categoria': [''],
                'Descrição': [''],
                'Valor': ['']
            })
            
        elif expense_type == 'recurring':
            # Criar DataFrame com uma linha vazia para despesa recorrente
            df = pd.DataFrame({
                'Data': [''],
                'Categoria': [''],
                'Descrição': [''],
                'Valor': [''],
                'Tipo de Recorrência': [''],
                'Data Final da Recorrência': ['']
            })
            
        elif expense_type == 'installment':
            # Criar DataFrame com uma linha vazia para despesa parcelada
            df = pd.DataFrame({
                'Data': [''],
                'Categoria': [''],
                'Descrição': [''],
                'Valor': [''],
                'Número da Parcela': [''],
                'Total de Parcelas': ['']
            })
        
        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Get the worksheet and set column widths
            worksheet = writer.sheets[sheet_name]
            workbook = writer.book
            
            for i, col in enumerate(df.columns):
                # Set column width based on content
                max_len = max(df[col].astype(str).apply(len).max(), len(col)) + 2
                worksheet.set_column(i, i, max_len)
            
            # Find the column index for 'Categoria'
            category_col = None
            for i, col in enumerate(df.columns):
                if col == 'Categoria':
                    category_col = i
                    break
            
            # Add dropdown for categories in all export types
            if category_col is not None:
                # Add a data validation to the category column
                worksheet.data_validation(
                    1, category_col, 1000, category_col,
                    {
                        'validate': 'list',
                        'source': categories,
                        'input_title': 'Selecione a categoria',
                        'input_message': 'Escolha uma categoria da lista',
                        'error_title': 'Categoria inválida',
                        'error_message': 'Por favor, selecione uma categoria da lista.'
                    }
                )
                
            # Add dropdown for recurring type if this is a recurring expense export
            if expense_type == 'recurring':
                # Find the column index for 'Tipo de Recorrência'
                recurring_type_col = None
                for i, col in enumerate(df.columns):
                    if col == 'Tipo de Recorrência':
                        recurring_type_col = i
                        break
                
                if recurring_type_col is not None:
                    # Create a dropdown list with the recurring types
                    dropdown_options = ['monthly', 'yearly', 'weekly']
                    
                    # Add a data validation to the column
                    # The first row (0) is the header, so we start from row 1
                    # We apply the validation to all rows in the worksheet (up to 1000 for safety)
                    worksheet.data_validation(
                        1, recurring_type_col, 1000, recurring_type_col,
                        {
                            'validate': 'list',
                            'source': dropdown_options,
                            'input_title': 'Selecione o tipo de recorrência',
                            'input_message': 'Escolha entre mensal, anual ou semanal',
                            'error_title': 'Entrada inválida',
                            'error_message': 'Por favor, selecione uma das opções da lista.'
                        }
                    )
        
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except mysql.connector.Error as err:
        print(f"Error exporting expenses: {err}")
        flash(f'Erro ao exportar despesas: {err}', 'danger')
        return redirect(url_for('expenses.expenses_list'))
    finally:
        cursor.close()
        conn.close()

# Import expenses route
@expenses_bp.route('/import', methods=['POST'])
@login_required
def import_expenses():
    if 'import_file' not in request.files:
        flash('Nenhum arquivo selecionado', 'danger')
        return redirect(url_for('expenses.expenses_list'))
    
    file = request.files['import_file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado', 'danger')
        return redirect(url_for('expenses.expenses_list'))
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        flash('Formato de arquivo inválido. Por favor, envie um arquivo Excel (.xlsx ou .xls)', 'danger')
        return redirect(url_for('expenses.expenses_list'))
    
    try:
        # Read Excel file
        df = pd.read_excel(file)
        
        # Check if dataframe is empty
        if df.empty:
            flash('O arquivo está vazio', 'warning')
            return redirect(url_for('expenses.expenses_list'))
        
        # Determine expense type based on columns
        expense_type = 'unknown'
        if 'Tipo de Recorrência' in df.columns and 'Data Final da Recorrência' in df.columns:
            expense_type = 'recurring'
        elif 'Número da Parcela' in df.columns and 'Total de Parcelas' in df.columns:
            expense_type = 'installment'
        elif set(['Data', 'Categoria', 'Descrição', 'Valor']).issubset(df.columns):
            expense_type = 'single'
        
        if expense_type == 'unknown':
            flash('Formato de arquivo inválido. O arquivo não contém as colunas esperadas.', 'danger')
            return redirect(url_for('expenses.expenses_list'))
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get expense categories
        cursor.execute('SELECT id, name FROM expense_categories')
        categories = {category['name']: category['id'] for category in cursor.fetchall()}
        
        # Process rows based on expense type
        success_count = 0
        error_count = 0
        
        for _, row in df.iterrows():
            try:
                # Skip rows with empty essential data
                if pd.isna(row['Data']) or pd.isna(row['Categoria']) or pd.isna(row['Valor']):
                    continue
                
                # Convert date to string format if it's a datetime object
                date = row['Data']
                if isinstance(date, pd.Timestamp):
                    date = date.strftime('%Y-%m-%d')
                
                # Get category ID
                category_name = row['Categoria']
                if category_name not in categories:
                    # Create new category if it doesn't exist
                    cursor.execute(
                        'INSERT INTO expense_categories (name, description) VALUES (%s, %s)',
                        (category_name, f'Categoria importada: {category_name}')
                    )
                    conn.commit()
                    
                    # Get the new category ID
                    cursor.execute('SELECT LAST_INSERT_ID() as id')
                    category_id = cursor.fetchone()['id']
                    categories[category_name] = category_id
                else:
                    category_id = categories[category_name]
                
                # Get description (handle NaN values)
                description = row['Descrição'] if not pd.isna(row['Descrição']) else ''
                
                # Get amount
                amount = float(row['Valor'])
                
                if expense_type == 'single':
                    # Insert single expense
                    cursor.execute(
                        'INSERT INTO expenses (user_id, category_id, amount, description, date) VALUES (%s, %s, %s, %s, %s)',
                        (session['user_id'], category_id, amount, description, date)
                    )
                    
                elif expense_type == 'recurring':
                    # Get recurring type and end date
                    recurring_type = row['Tipo de Recorrência']
                    recurring_end_date = row['Data Final da Recorrência']
                    
                    # Convert end date to string format if it's a datetime object
                    if isinstance(recurring_end_date, pd.Timestamp):
                        recurring_end_date = recurring_end_date.strftime('%Y-%m-%d')
                    
                    # Insert recurring expense
                    cursor.execute(
                        '''
                        INSERT INTO expenses 
                        (user_id, category_id, amount, description, date, is_recurring, recurring_type, recurring_end_date) 
                        VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s)
                        ''',
                        (session['user_id'], category_id, amount, description, date, recurring_type, recurring_end_date)
                    )
                    
                elif expense_type == 'installment':
                    # Get installment details
                    total_installments = int(row['Total de Parcelas'])
                    
                    # Insert parent expense
                    cursor.execute(
                        '''
                        INSERT INTO expenses 
                        (user_id, category_id, amount, description, date, is_installment, total_installments) 
                        VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                        ''',
                        (session['user_id'], category_id, amount, description, date, total_installments)
                    )
                    
                    # Get parent expense ID
                    cursor.execute('SELECT LAST_INSERT_ID() as id')
                    parent_id = cursor.fetchone()['id']
                    
                    # Create installments
                    installment_date = datetime.strptime(date, '%Y-%m-%d') if isinstance(date, str) else date
                    installment_amount = amount / total_installments
                    
                    for i in range(1, total_installments + 1):
                        # Calculate installment date (add i-1 months to the original date)
                        current_installment_date = installment_date.replace(month=((installment_date.month + i - 1 - 1) % 12) + 1)
                        if (installment_date.month + i - 1) > 12:
                            current_installment_date = current_installment_date.replace(year=current_installment_date.year + ((installment_date.month + i - 1 - 1) // 12))
                        
                        # Format date as string
                        current_installment_date_str = current_installment_date.strftime('%Y-%m-%d')
                        
                        # Insert installment
                        cursor.execute(
                            '''
                            INSERT INTO expenses 
                            (user_id, category_id, amount, description, date, is_installment, parent_expense_id, installment_number, total_installments) 
                            VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                            ''',
                            (session['user_id'], category_id, installment_amount, description, current_installment_date_str, 
                             parent_id, i, total_installments)
                        )
                
                conn.commit()
                success_count += 1
                
            except Exception as e:
                conn.rollback()
                print(f"Error importing row: {e}")
                error_count += 1
        
        if success_count > 0:
            flash(f'{success_count} despesas importadas com sucesso.', 'success')
        if error_count > 0:
            flash(f'{error_count} despesas não puderam ser importadas devido a erros.', 'warning')
        
        return redirect(url_for('expenses.expenses_list'))
        
    except Exception as e:
        print(f"Error importing expenses: {e}")
        flash(f'Erro ao importar despesas: {e}', 'danger')
        return redirect(url_for('expenses.expenses_list'))

# Rota de exclusão de despesas movida para cima no arquivo

# Investments routes
@investments_bp.route('/investments')
@login_required
def investments_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Prepare filters
    filters = ["i.user_id = %s"]
    params = [session['user_id']]
    
    # Filter by type
    type_id = request.args.get('type_id')
    if type_id and type_id.isdigit() and int(type_id) > 0:
        filters.append("i.type_id = %s")
        params.append(int(type_id))
    
    # Filter by start date
    start_date = request.args.get('start_date')
    if start_date:
        filters.append("i.date >= %s")
        params.append(start_date)
    
    # Filter by end date
    end_date = request.args.get('end_date')
    if end_date:
        filters.append("i.date <= %s")
        params.append(end_date)
    
    # Build the query with filters
    query = f'''
        SELECT i.*, t.name as type_name 
        FROM investments i 
        JOIN investment_types t ON i.type_id = t.id 
        WHERE {' AND '.join(filters)} 
        ORDER BY i.date DESC
    '''
    
    try:
        cursor.execute(query, tuple(params))
        investments = cursor.fetchall()
        
        # Calculate total investment value
        total_value = 0
        for investment in investments:
            total_value += float(investment['amount'])
            
    except mysql.connector.Error as err:
        print(f"Error retrieving investments: {err}")
        investments = []
        total_value = 0
    
    # Get investment types for the form
    cursor.execute('SELECT * FROM investment_types ORDER BY name')
    types = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('investments/list.html', investments=investments, types=types, total_value=total_value)

@investments_bp.route('/investments/add', methods=['GET', 'POST'])
@login_required
def add_investment():
    if request.method == 'POST':
        type_id = request.form['type_id']
        amount = request.form['amount']
        description = request.form['description']
        date = request.form['date']
        expected_return = request.form['expected_return'] or None
        maturity_date = request.form['maturity_date'] or None
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO investments (user_id, type_id, amount, description, date, expected_return, maturity_date) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (session['user_id'], type_id, amount, description, date, expected_return, maturity_date)
            )
            conn.commit()
            flash('Investimento adicionado com sucesso!', 'success')
        except mysql.connector.Error as err:
            print(f"Error adding investment: {err}")
            flash(f'Erro ao adicionar investimento: {err}', 'danger')
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('investments.investments_list'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get investment types for the form
    try:
        cursor.execute('SELECT * FROM investment_types ORDER BY name')
        types = cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error retrieving investment types: {err}")
        types = []
        flash('Erro ao carregar tipos de investimento. Por favor, tente novamente.', 'warning')
    finally:
        cursor.close()
        conn.close()
    
    return render_template('investments/add.html', types=types)

@investments_bp.route('/investments/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_investment(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        type_id = request.form['type_id']
        amount = request.form['amount']
        description = request.form['description']
        date = request.form['date']
        expected_return = request.form['expected_return'] or None
        maturity_date = request.form['maturity_date'] or None
        
        cursor.execute(
            'UPDATE investments SET type_id = %s, amount = %s, description = %s, date = %s, expected_return = %s, maturity_date = %s WHERE id = %s AND user_id = %s',
            (type_id, amount, description, date, expected_return, maturity_date, id, session['user_id'])
        )
        conn.commit()
        
        flash('Investimento atualizado com sucesso!', 'success')
        return redirect(url_for('investments.investments_list'))
    
    # Get the investment
    cursor.execute('SELECT * FROM investments WHERE id = %s AND user_id = %s', (id, session['user_id']))
    investment = cursor.fetchone()
    
    if not investment:
        flash('Investimento não encontrado.', 'danger')
        return redirect(url_for('investments.investments_list'))
    
    # Get investment types for the form
    cursor.execute('SELECT * FROM investment_types ORDER BY name')
    types = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('investments/edit.html', investment=investment, types=types)

@investments_bp.route('/investments/delete/<int:id>')
@login_required
def delete_investment(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM investments WHERE id = %s AND user_id = %s', (id, session['user_id']))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    flash('Investimento excluído com sucesso!', 'success')
    return redirect(url_for('investments.investments_list'))

@investments_bp.route('/export', methods=['POST'])
@login_required
def export_investments():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get investment types for the dropdown
    cursor.execute('SELECT name, risk_level FROM investment_types ORDER BY name')
    types = cursor.fetchall()
    
    # Create template with a blank row for filling
    df = pd.DataFrame({
        'Data': [''],
        'Tipo de Investimento': [''],
        'Descrição': [''],
        'Valor': [''],
        'Retorno Esperado (%)': [''],
        'Data de Vencimento': ['']
    })
    
    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Investimentos', index=False)
        
        # Get the worksheet and set column widths
        worksheet = writer.sheets['Investimentos']
        workbook = writer.book
        
        for i, col in enumerate(df.columns):
            # Set column width based on content
            max_len = max(df[col].astype(str).apply(len).max(), len(col)) + 2
            worksheet.set_column(i, i, max_len)
        
        # Find the column index for 'Tipo de Investimento'
        type_col = None
        for i, col in enumerate(df.columns):
            if col == 'Tipo de Investimento':
                type_col = i
                break
        
        # Add dropdown for investment types
        if type_col is not None:
            # Create a list of investment type names with risk level
            type_options = [f"{t['name']} (Risco: {t['risk_level']})" for t in types]
            
            # Add a data validation to the investment type column
            worksheet.data_validation(
                1, type_col, 1000, type_col,
                {
                    'validate': 'list',
                    'source': type_options,
                    'input_title': 'Selecione o tipo de investimento',
                    'input_message': 'Escolha um tipo de investimento da lista',
                    'error_title': 'Tipo de investimento inválido',
                    'error_message': 'Por favor, selecione um tipo de investimento da lista.'
                }
            )
    
    cursor.close()
    conn.close()
    
    # Set up response headers for file download
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name='modelo_investimentos.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@investments_bp.route('/import', methods=['POST'])
@login_required
def import_investments():
    if 'import_file' not in request.files:
        flash('Nenhum arquivo selecionado', 'danger')
        return redirect(url_for('investments.investments_list'))
    
    file = request.files['import_file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado', 'danger')
        return redirect(url_for('investments.investments_list'))
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        flash('Formato de arquivo inválido. Por favor, envie um arquivo Excel (.xlsx ou .xls)', 'danger')
        return redirect(url_for('investments.investments_list'))
    
    try:
        # Read Excel file
        df = pd.read_excel(file)
        
        # Check if dataframe is empty
        if df.empty:
            flash('O arquivo está vazio', 'warning')
            return redirect(url_for('investments.investments_list'))
        
        # Check if the file has the expected columns
        expected_columns = ['Data', 'Tipo de Investimento', 'Descrição', 'Valor', 'Retorno Esperado (%)', 'Data de Vencimento']
        if not set(expected_columns).issubset(df.columns):
            flash('Formato de arquivo inválido. O arquivo não contém as colunas esperadas.', 'danger')
            return redirect(url_for('investments.investments_list'))
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get investment types
        cursor.execute('SELECT id, name, risk_level FROM investment_types')
        types_db = cursor.fetchall()
        
        # Create a mapping of type names to IDs
        types = {}
        for t in types_db:
            # Map both the name and the name with risk level
            types[t['name']] = t['id']
            types[f"{t['name']} (Risco: {t['risk_level']})"] = t['id']
        
        # Process rows
        success_count = 0
        error_count = 0
        
        for _, row in df.iterrows():
            try:
                # Skip rows with empty essential data
                if pd.isna(row['Data']) or pd.isna(row['Tipo de Investimento']) or pd.isna(row['Valor']):
                    continue
                
                # Convert date to string format if it's a datetime object
                date = row['Data']
                if isinstance(date, pd.Timestamp):
                    date = date.strftime('%Y-%m-%d')
                
                # Get investment type ID
                type_name = row['Tipo de Investimento']
                if type_name not in types:
                    # If the type doesn't exist, we'll extract just the name part (before any parentheses)
                    clean_type_name = type_name.split(' (')[0] if ' (' in type_name else type_name
                    
                    # Check if the clean name exists
                    if clean_type_name in types:
                        type_id = types[clean_type_name]
                    else:
                        # Create new type if it doesn't exist (with Medium risk level as default)
                        cursor.execute(
                            'INSERT INTO investment_types (name, description, risk_level) VALUES (%s, %s, %s)',
                            (clean_type_name, f'Tipo importado: {clean_type_name}', 'Medium')
                        )
                        conn.commit()
                        
                        # Get the new type ID
                        cursor.execute('SELECT LAST_INSERT_ID() as id')
                        type_id = cursor.fetchone()['id']
                        types[clean_type_name] = type_id
                else:
                    type_id = types[type_name]
                
                # Get description (handle NaN values)
                description = row['Descrição'] if not pd.isna(row['Descrição']) else ''
                
                # Get amount
                amount = float(row['Valor'])
                
                # Get expected return (handle NaN values)
                expected_return = None
                if not pd.isna(row['Retorno Esperado (%)']):
                    expected_return = float(row['Retorno Esperado (%)'])
                
                # Get maturity date (handle NaN values)
                maturity_date = None
                if not pd.isna(row['Data de Vencimento']):
                    maturity_date = row['Data de Vencimento']
                    if isinstance(maturity_date, pd.Timestamp):
                        maturity_date = maturity_date.strftime('%Y-%m-%d')
                
                # Insert investment
                cursor.execute(
                    'INSERT INTO investments (user_id, type_id, amount, description, date, expected_return, maturity_date) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (session['user_id'], type_id, amount, description, date, expected_return, maturity_date)
                )
                conn.commit()
                success_count += 1
                
            except Exception as e:
                print(f"Error importing investment: {e}")
                error_count += 1
                continue
        
        if success_count > 0:
            flash(f'{success_count} investimentos importados com sucesso!', 'success')
        if error_count > 0:
            flash(f'{error_count} investimentos não puderam ser importados devido a erros.', 'warning')
        if success_count == 0 and error_count == 0:
            flash('Nenhum investimento válido encontrado no arquivo.', 'warning')
            
    except Exception as e:
        flash(f'Erro ao processar o arquivo: {str(e)}', 'danger')
        print(f"Error processing import file: {e}")
    
    return redirect(url_for('investments.investments_list'))

# Income routes
@income_bp.route('/income')
@login_required
def income_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Prepare filters
    filters = ["i.user_id = %s"]
    params = [session['user_id']]
    
    # Filter by source
    source_id = request.args.get('source_id')
    if source_id and source_id.isdigit() and int(source_id) > 0:
        filters.append("i.source_id = %s")
        params.append(int(source_id))
    
    # Filter by date range
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Validar que a data final não é menor que a data inicial
    if start_date and end_date and end_date < start_date:
        flash('A data final não pode ser menor que a data inicial.', 'danger')
        # Redefine a data final para ser igual à data inicial
        end_date = start_date
    
    if start_date:
        filters.append("i.date >= %s")
        params.append(start_date)
    
    if end_date:
        filters.append("i.date <= %s")
        params.append(end_date)
    
    # Build the SQL query with filters
    query = f'''
        SELECT i.*, s.name as source_name 
        FROM income i 
        JOIN income_sources s ON i.source_id = s.id 
        WHERE {' AND '.join(filters)} 
        ORDER BY i.date DESC
    '''
    
    # Execute the query with parameters
    cursor.execute(query, tuple(params))
    income_entries = cursor.fetchall()
    
    # Calculate total income
    total_income = 0
    for income in income_entries:
        total_income += float(income['amount'])
    
    # Get income sources for the form
    cursor.execute('SELECT * FROM income_sources ORDER BY name')
    sources = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('income/list.html', income_entries=income_entries, sources=sources, total_income=total_income)

@income_bp.route('/income/add', methods=['GET', 'POST'])
@login_required
def add_income():
    if request.method == 'POST':
        source_id = request.form['source_id']
        amount = request.form['amount']
        description = request.form['description']
        date = request.form['date']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO income (user_id, source_id, amount, description, date) VALUES (%s, %s, %s, %s, %s)',
            (session['user_id'], source_id, amount, description, date)
        )
        conn.commit()
        
        cursor.close()
        conn.close()
        
        flash('Receita adicionada com sucesso!', 'success')
        return redirect(url_for('income.income_list'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get income sources for the form
    cursor.execute('SELECT * FROM income_sources ORDER BY name')
    sources = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('income/add.html', sources=sources)

@income_bp.route('/income/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_income(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        source_id = request.form['source_id']
        amount = request.form['amount']
        description = request.form['description']
        date = request.form['date']
        
        cursor.execute(
            'UPDATE income SET source_id = %s, amount = %s, description = %s, date = %s WHERE id = %s AND user_id = %s',
            (source_id, amount, description, date, id, session['user_id'])
        )
        conn.commit()
        
        flash('Receita atualizada com sucesso!', 'success')
        return redirect(url_for('income.income_list'))
    
    # Get the income entry
    cursor.execute('SELECT * FROM income WHERE id = %s AND user_id = %s', (id, session['user_id']))
    income = cursor.fetchone()
    
    if not income:
        flash('Receita não encontrada.', 'danger')
        return redirect(url_for('income.income_list'))
    
    # Get income sources for the form
    cursor.execute('SELECT * FROM income_sources ORDER BY name')
    sources = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('income/edit.html', income=income, sources=sources)

@income_bp.route('/income/delete/<int:id>')
@login_required
def delete_income(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM income WHERE id = %s AND user_id = %s', (id, session['user_id']))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    flash('Receita excluída com sucesso!', 'success')
    return redirect(url_for('income.income_list'))

@income_bp.route('/income/export', methods=['POST'])
@login_required
def export_income():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get all income sources for data validation
    cursor.execute('SELECT name FROM income_sources ORDER BY name')
    income_sources = [source['name'] for source in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    # Create an empty template DataFrame
    df = pd.DataFrame({
        'Data': [''],
        'Fonte': [''],
        'Valor': [''],
        'Descrição': ['']
    })
    
    # Create a BytesIO object to store the Excel file
    output = io.BytesIO()
    
    # Write the DataFrame to the Excel file
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Receitas', index=False)
        
        # Get the workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets['Receitas']
        
        # Create a new sheet for the source list
        source_sheet = workbook.create_sheet(title='FontesLista')
        for i, source in enumerate(income_sources):
            source_sheet.cell(row=i+1, column=1, value=source)
        
        # Add data validation to the Fonte column (column B, starting from row 2)
        # First, determine the last row with sources in the FontesLista sheet
        last_row = len(income_sources)
        
        # Add data validation to the Fonte column in the main sheet
        # Column B is the Fonte column (index 2 in openpyxl)
        from openpyxl.worksheet.datavalidation import DataValidation
        dv = DataValidation(
            type="list",
            formula1=f"=FontesLista!$A$1:$A${last_row}",
            allow_blank=True
        )
        worksheet.add_data_validation(dv)
        
        # Apply validation to all cells in the Fonte column (excluding header)
        # Find the last row in the data
        data_last_row = len(df) + 1  # +1 for the header
        for i in range(2, data_last_row + 10):  # Add some extra rows for new entries
            dv.add(f"B{i}")
    
    # Set the file pointer to the beginning of the file
    output.seek(0)
    
    # Create a response with the Excel file
    return send_file(
        output,
        as_attachment=True,
        download_name='receitas.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@income_bp.route('/income/import', methods=['POST'])
@login_required
def import_income():
    if 'import_file' not in request.files:
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('income.income_list'))
    
    file = request.files['import_file']
    
    if file.filename == '':
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('income.income_list'))
    
    if not file.filename.endswith('.xlsx'):
        flash('Formato de arquivo inválido. Por favor, selecione um arquivo Excel (.xlsx).', 'danger')
        return redirect(url_for('income.income_list'))
    
    try:
        # Read the Excel file
        df = pd.read_excel(file)
        
        # Check if the required columns are present
        required_columns = ['Fonte', 'Valor', 'Descrição', 'Data']
        for column in required_columns:
            if column not in df.columns:
                flash(f'Coluna {column} não encontrada no arquivo.', 'danger')
                return redirect(url_for('income.income_list'))
        
        # Connect to the database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get income sources
        cursor.execute('SELECT id, name FROM income_sources')
        sources = {source['name']: source['id'] for source in cursor.fetchall()}
        
        # Process each row in the DataFrame
        success_count = 0
        error_count = 0
        
        for _, row in df.iterrows():
            try:
                # Get the source ID from the source name
                source_name = row['Fonte']
                if source_name not in sources:
                    # Create a new source if it doesn't exist
                    cursor.execute(
                        'INSERT INTO income_sources (name, description) VALUES (%s, %s)',
                        (source_name, f'Importado em {datetime.now().strftime("%d/%m/%Y")}')
                    )
                    conn.commit()
                    
                    # Get the new source ID
                    cursor.execute('SELECT id FROM income_sources WHERE name = %s', (source_name,))
                    source_id = cursor.fetchone()['id']
                    sources[source_name] = source_id
                else:
                    source_id = sources[source_name]
                
                # Convert the date to the correct format
                date_str = row['Data']
                if isinstance(date_str, str):
                    # Try to parse the date string
                    try:
                        date_obj = datetime.strptime(date_str, '%d/%m/%Y')
                        date_formatted = date_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        # If the date format is not dd/mm/yyyy, try other formats
                        try:
                            date_obj = pd.to_datetime(date_str)
                            date_formatted = date_obj.strftime('%Y-%m-%d')
                        except:
                            raise ValueError(f'Formato de data inválido: {date_str}')
                else:
                    # If the date is already a datetime object
                    date_formatted = pd.to_datetime(date_str).strftime('%Y-%m-%d')
                
                # Insert the income entry
                cursor.execute(
                    'INSERT INTO income (user_id, source_id, amount, description, date) VALUES (%s, %s, %s, %s, %s)',
                    (session['user_id'], source_id, float(row['Valor']), row['Descrição'], date_formatted)
                )
                conn.commit()
                success_count += 1
            except Exception as e:
                print(f'Error importing row: {e}')
                error_count += 1
                continue
        
        cursor.close()
        conn.close()
        
        if success_count > 0:
            flash(f'{success_count} receitas importadas com sucesso!', 'success')
        
        if error_count > 0:
            flash(f'{error_count} receitas não puderam ser importadas devido a erros.', 'warning')
        
        return redirect(url_for('income.income_list'))
    except Exception as e:
        flash(f'Erro ao importar arquivo: {str(e)}', 'danger')
        return redirect(url_for('income.income_list'))

# Categories and types management
@categories_bp.route('/categories')
@login_required
def categories_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get expense categories (both system defaults and user-specific)
    cursor.execute(
        'SELECT * FROM expense_categories WHERE user_id IS NULL OR user_id = %s ORDER BY name',
        (session['user_id'],)
    )
    expense_categories = cursor.fetchall()
    
    # Get investment types (both system defaults and user-specific)
    cursor.execute(
        'SELECT * FROM investment_types WHERE user_id IS NULL OR user_id = %s ORDER BY name',
        (session['user_id'],)
    )
    investment_types = cursor.fetchall()
    
    # Get income sources (both system defaults and user-specific)
    cursor.execute(
        'SELECT * FROM income_sources WHERE user_id IS NULL OR user_id = %s ORDER BY name',
        (session['user_id'],)
    )
    income_sources = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('categories/list.html', 
                          expense_categories=expense_categories,
                          investment_types=investment_types,
                          income_sources=income_sources)

# Expense categories
@categories_bp.route('/categories/expense/add', methods=['POST'])
@login_required
def add_expense_category():
    name = request.form['name']
    description = request.form['description']
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'INSERT INTO expense_categories (user_id, name, description) VALUES (%s, %s, %s)',
            (user_id, name, description)
        )
        conn.commit()
        flash('Categoria de despesa adicionada com sucesso!', 'success')
    except:
        flash('Erro ao adicionar categoria. Verifique se já existe uma categoria com este nome.', 'danger')
    
    cursor.close()
    conn.close()
    
    return redirect(url_for('categories.categories_list'))

@categories_bp.route('/categories/expense/edit/<int:id>', methods=['POST'])
@login_required
def edit_expense_category(id):
    name = request.form['name']
    description = request.form['description']
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Check if this is a user-specific category
    cursor.execute('SELECT * FROM expense_categories WHERE id = %s', (id,))
    category = cursor.fetchone()
    
    if not category or (category['user_id'] is None):
        flash('Você não pode editar categorias padrão do sistema.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('categories.categories_list'))
    
    if category['user_id'] != user_id:
        flash('Você só pode editar suas próprias categorias.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('categories.categories_list'))
    
    try:
        cursor.execute(
            'UPDATE expense_categories SET name = %s, description = %s WHERE id = %s AND user_id = %s',
            (name, description, id, user_id)
        )
        conn.commit()
        flash('Categoria de despesa atualizada com sucesso!', 'success')
    except:
        flash('Erro ao atualizar categoria. Verifique se já existe uma categoria com este nome.', 'danger')
    
    cursor.close()
    conn.close()
    
    return redirect(url_for('categories.categories_list'))

# Investment types
@categories_bp.route('/categories/investment/add', methods=['POST'])
@login_required
def add_investment_type():
    name = request.form['name']
    description = request.form['description']
    risk_level = request.form['risk_level']
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'INSERT INTO investment_types (user_id, name, description, risk_level) VALUES (%s, %s, %s, %s)',
            (user_id, name, description, risk_level)
        )
        conn.commit()
        flash('Tipo de investimento adicionado com sucesso!', 'success')
    except:
        flash('Erro ao adicionar tipo de investimento. Verifique se já existe um tipo com este nome.', 'danger')
    
    cursor.close()
    conn.close()
    
    return redirect(url_for('categories.categories_list'))

@categories_bp.route('/categories/investment/edit/<int:id>', methods=['POST'])
@login_required
def edit_investment_type(id):
    name = request.form['name']
    description = request.form['description']
    risk_level = request.form['risk_level']
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Check if this is a user-specific category
    cursor.execute('SELECT * FROM investment_types WHERE id = %s', (id,))
    inv_type = cursor.fetchone()
    
    if not inv_type or (inv_type['user_id'] is None):
        flash('Você não pode editar tipos de investimento padrão do sistema.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('categories.categories_list'))
    
    if inv_type['user_id'] != user_id:
        flash('Você só pode editar seus próprios tipos de investimento.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('categories.categories_list'))
    
    try:
        cursor.execute(
            'UPDATE investment_types SET name = %s, description = %s, risk_level = %s WHERE id = %s AND user_id = %s',
            (name, description, risk_level, id, user_id)
        )
        conn.commit()
        flash('Tipo de investimento atualizado com sucesso!', 'success')
    except:
        flash('Erro ao atualizar tipo de investimento. Verifique se já existe um tipo com este nome.', 'danger')
    
    cursor.close()
    conn.close()
    
    return redirect(url_for('categories.categories_list'))

# Income sources
@categories_bp.route('/categories/income/add', methods=['POST'])
@login_required
def add_income_source():
    name = request.form['name']
    description = request.form['description']
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'INSERT INTO income_sources (user_id, name, description) VALUES (%s, %s, %s)',
            (user_id, name, description)
        )
        conn.commit()
        flash('Fonte de receita adicionada com sucesso!', 'success')
    except:
        flash('Erro ao adicionar fonte de receita. Verifique se já existe uma fonte com este nome.', 'danger')
    
    cursor.close()
    conn.close()
    
    return redirect(url_for('categories.categories_list'))

@categories_bp.route('/categories/income/edit/<int:id>', methods=['POST'])
@login_required
def edit_income_source(id):
    name = request.form['name']
    description = request.form['description']
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Check if this is a user-specific category
    cursor.execute('SELECT * FROM income_sources WHERE id = %s', (id,))
    source = cursor.fetchone()
    
    if not source or (source['user_id'] is None):
        flash('Você não pode editar fontes de receita padrão do sistema.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('categories.categories_list'))
    
    if source['user_id'] != user_id:
        flash('Você só pode editar suas próprias fontes de receita.', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('categories.categories_list'))
    
    try:
        cursor.execute(
            'UPDATE income_sources SET name = %s, description = %s WHERE id = %s AND user_id = %s',
            (name, description, id, user_id)
        )
        conn.commit()
        flash('Fonte de receita atualizada com sucesso!', 'success')
    except:
        flash('Erro ao atualizar fonte de receita. Verifique se já existe uma fonte com este nome.', 'danger')
    
    cursor.close()
    conn.close()
    
    return redirect(url_for('categories.categories_list'))

# Budget management
@budgets_bp.route('/budgets')
@login_required
def budgets_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get all budgets for the user with spent amounts
    try:
        cursor.execute('''
            SELECT b.*, c.name as category_name,
            (SELECT COALESCE(SUM(e.amount), 0)
             FROM expenses e
             WHERE e.user_id = b.user_id
             AND e.category_id = b.category_id
             AND e.date BETWEEN b.start_date AND b.end_date) as spent
            FROM budgets b 
            JOIN expense_categories c ON b.category_id = c.id 
            WHERE b.user_id = %s 
            ORDER BY b.start_date DESC
        ''', (session['user_id'],))
        budgets = cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error retrieving budgets: {err}")
        budgets = []
    
    # Get expense categories for the form
    cursor.execute('SELECT * FROM expense_categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('budgets/list.html', budgets=budgets, categories=categories)

@budgets_bp.route('/budgets/add', methods=['GET', 'POST'])
@login_required
def add_budget():
    if request.method == 'POST':
        category_id = request.form['category_id']
        amount = request.form['amount']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        
        # Validar que a data final não é menor que a data inicial
        if start_date and end_date and end_date < start_date:
            flash('A data final não pode ser menor que a data inicial.', 'danger')
            
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Get expense categories for the form
            cursor.execute('SELECT * FROM expense_categories ORDER BY name')
            categories = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            return render_template('budgets/add.html', categories=categories)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO budgets (user_id, category_id, amount, start_date, end_date) VALUES (%s, %s, %s, %s, %s)',
                (session['user_id'], category_id, amount, start_date, end_date)
            )
            conn.commit()
            flash('Orçamento adicionado com sucesso!', 'success')
            return redirect(url_for('budgets.budgets_list'))
        except:
            flash('Erro ao adicionar orçamento. Verifique se já existe um orçamento para esta categoria e período.', 'danger')
        
        cursor.close()
        conn.close()
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get expense categories for the form
    cursor.execute('SELECT * FROM expense_categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('budgets/add.html', categories=categories)

@budgets_bp.route('/budgets/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_budget(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        category_id = request.form['category_id']
        amount = request.form['amount']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        
        # Validar que a data final não é menor que a data inicial
        if start_date and end_date and end_date < start_date:
            flash('A data final não pode ser menor que a data inicial.', 'danger')
            
            # Get the budget
            cursor.execute('SELECT * FROM budgets WHERE id = %s AND user_id = %s', (id, session['user_id']))
            budget = cursor.fetchone()
            
            if not budget:
                flash('Orçamento não encontrado.', 'danger')
                return redirect(url_for('budgets.budgets_list'))
            
            # Get expense categories for the form
            cursor.execute('SELECT * FROM expense_categories ORDER BY name')
            categories = cursor.fetchall()
            
            return render_template('budgets/edit.html', budget=budget, categories=categories)
        
        try:
            cursor.execute(
                'UPDATE budgets SET category_id = %s, amount = %s, start_date = %s, end_date = %s WHERE id = %s AND user_id = %s',
                (category_id, amount, start_date, end_date, id, session['user_id'])
            )
            conn.commit()
            flash('Orçamento atualizado com sucesso!', 'success')
            return redirect(url_for('budgets.budgets_list'))
        except:
            flash('Erro ao atualizar orçamento. Verifique se já existe um orçamento para esta categoria e período.', 'danger')
    
    # Get the budget
    cursor.execute('SELECT * FROM budgets WHERE id = %s AND user_id = %s', (id, session['user_id']))
    budget = cursor.fetchone()
    
    if not budget:
        flash('Orçamento não encontrado.', 'danger')
        return redirect(url_for('budgets.budgets_list'))
    
    # Get expense categories for the form
    cursor.execute('SELECT * FROM expense_categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('budgets/edit.html', budget=budget, categories=categories)

@budgets_bp.route('/budgets/delete/<int:id>')
@login_required
def delete_budget(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM budgets WHERE id = %s AND user_id = %s', (id, session['user_id']))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    flash('Orçamento excluído com sucesso!', 'success')
    return redirect(url_for('budgets.budgets_list'))

# API routes for charts and data
@expenses_bp.route('/api/expenses/monthly')
@login_required
def api_monthly_expenses():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Obter o ano atual
    current_year = datetime.now().year
    
    # Consulta para despesas normais (não recorrentes e não parceladas)
    cursor.execute('''
        SELECT SUM(amount) as total, MONTH(date) as month, YEAR(date) as year
        FROM expenses
        WHERE user_id = %s 
        AND YEAR(date) = %s
        AND (is_recurring = FALSE OR is_recurring IS NULL)
        AND (is_installment = FALSE OR is_installment IS NULL)
        GROUP BY YEAR(date), MONTH(date)
        ORDER BY year, month
    ''', (session['user_id'], current_year))
    regular_expenses = cursor.fetchall()
    
    # Consulta para despesas parceladas
    cursor.execute('''
        SELECT 
            MONTH(DATE_ADD(date, INTERVAL n MONTH)) as month,
            YEAR(DATE_ADD(date, INTERVAL n MONTH)) as year,
            SUM(amount / total_installments) as total
        FROM 
            expenses,
            (SELECT 0 as n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION
             SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION
             SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11) as numbers
        WHERE 
            user_id = %s 
            AND is_installment = TRUE
            AND YEAR(DATE_ADD(date, INTERVAL n MONTH)) = %s
            AND n < total_installments
            AND DATE_ADD(date, INTERVAL n MONTH) <= CURDATE()
        GROUP BY 
            YEAR(DATE_ADD(date, INTERVAL n MONTH)),
            MONTH(DATE_ADD(date, INTERVAL n MONTH))
        ORDER BY 
            year, month
    ''', (session['user_id'], current_year))
    installment_expenses = cursor.fetchall()
    
    # Consulta para despesas recorrentes
    cursor.execute('''
        SELECT 
            MONTH(DATE_ADD(date, INTERVAL n MONTH)) as month,
            YEAR(DATE_ADD(date, INTERVAL n MONTH)) as year,
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
            AND (recurring_end_date IS NULL OR DATE_ADD(date, INTERVAL n MONTH) <= recurring_end_date)
        GROUP BY 
            YEAR(DATE_ADD(date, INTERVAL n MONTH)),
            MONTH(DATE_ADD(date, INTERVAL n MONTH))
        ORDER BY 
            year, month
    ''', (session['user_id'], current_year))
    recurring_monthly_expenses = cursor.fetchall()
    
    # Consulta para despesas recorrentes anuais
    cursor.execute('''
        SELECT 
            MONTH(date) as month,
            %s as year,
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
        ORDER BY 
            month
    ''', (current_year, session['user_id'], current_year))
    recurring_yearly_expenses = cursor.fetchall()
    
    # Combinar os resultados
    monthly_data = {}
    
    # Inicializar o dicionário com todos os meses do ano
    for month in range(1, 13):
        monthly_data[month] = {
            'month': month,
            'year': current_year,
            'total': 0
        }
    
    # Adicionar despesas normais
    for expense in regular_expenses:
        if expense['month'] in monthly_data:
            monthly_data[expense['month']]['total'] += float(expense['total'])
    
    # Adicionar despesas parceladas
    for expense in installment_expenses:
        if expense['month'] in monthly_data:
            monthly_data[expense['month']]['total'] += float(expense['total'])
    
    # Adicionar despesas recorrentes mensais
    for expense in recurring_monthly_expenses:
        if expense['month'] in monthly_data:
            monthly_data[expense['month']]['total'] += float(expense['total'])
    
    # Adicionar despesas recorrentes anuais
    for expense in recurring_yearly_expenses:
        if expense['month'] in monthly_data:
            monthly_data[expense['month']]['total'] += float(expense['total'])
    
    # Converter o dicionário para uma lista
    data = list(monthly_data.values())
    
    cursor.close()
    conn.close()
    
    return jsonify(data)

@expenses_bp.route('/api/expenses/by-category')
@login_required
def api_expenses_by_category():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Obter o mês e ano atual
    current_month = datetime.now().month
    current_year = datetime.now().year
    
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
    
    # Consulta para despesas parceladas por categoria para o mês atual
    cursor.execute('''
        SELECT 
            c.name, 
            SUM(e.amount / e.total_installments) as total
        FROM 
            expenses e
        JOIN 
            expense_categories c ON e.category_id = c.id,
            (SELECT 0 as n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION
             SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION
             SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11) as numbers
        WHERE 
            e.user_id = %s 
            AND e.is_installment = TRUE
            AND MONTH(DATE_ADD(e.date, INTERVAL n MONTH)) = %s
            AND YEAR(DATE_ADD(e.date, INTERVAL n MONTH)) = %s
            AND n < e.total_installments
            AND DATE_ADD(e.date, INTERVAL n MONTH) <= CURDATE()
        GROUP BY 
            c.name
    ''', (session['user_id'], current_month, current_year))
    installment_expense_categories = cursor.fetchall()
    
    # Consulta para despesas recorrentes mensais por categoria para o mês atual
    cursor.execute('''
        SELECT 
            c.name, 
            SUM(e.amount) as total
        FROM 
            expenses e
        JOIN 
            expense_categories c ON e.category_id = c.id,
            (SELECT 0 as n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION
             SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION
             SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11) as numbers
        WHERE 
            e.user_id = %s 
            AND e.is_recurring = TRUE
            AND e.recurring_type = 'monthly'
            AND MONTH(DATE_ADD(e.date, INTERVAL n MONTH)) = %s
            AND YEAR(DATE_ADD(e.date, INTERVAL n MONTH)) = %s
            AND (e.recurring_end_date IS NULL OR DATE_ADD(e.date, INTERVAL n MONTH) <= e.recurring_end_date)
        GROUP BY 
            c.name
    ''', (session['user_id'], current_month, current_year))
    recurring_monthly_expense_categories = cursor.fetchall()
    
    # Consulta para despesas recorrentes anuais por categoria para o mês atual
    cursor.execute('''
        SELECT 
            c.name, 
            SUM(e.amount) as total
        FROM 
            expenses e
        JOIN 
            expense_categories c ON e.category_id = c.id
        WHERE 
            e.user_id = %s 
            AND e.is_recurring = TRUE
            AND e.recurring_type = 'yearly'
            AND MONTH(e.date) = %s
            AND (e.recurring_end_date IS NULL OR %s <= YEAR(e.recurring_end_date))
        GROUP BY 
            c.name
    ''', (session['user_id'], current_month, current_year))
    recurring_yearly_expense_categories = cursor.fetchall()
    
    # Combinar os resultados
    expense_categories_dict = {}
    
    # Adicionar despesas normais
    for category in regular_expense_categories:
        expense_categories_dict[category['name']] = float(category['total'])
    
    # Adicionar despesas parceladas
    for category in installment_expense_categories:
        if category['name'] in expense_categories_dict:
            expense_categories_dict[category['name']] += float(category['total'])
        else:
            expense_categories_dict[category['name']] = float(category['total'])
    
    # Adicionar despesas recorrentes mensais
    for category in recurring_monthly_expense_categories:
        if category['name'] in expense_categories_dict:
            expense_categories_dict[category['name']] += float(category['total'])
        else:
            expense_categories_dict[category['name']] = float(category['total'])
    
    # Adicionar despesas recorrentes anuais
    for category in recurring_yearly_expense_categories:
        if category['name'] in expense_categories_dict:
            expense_categories_dict[category['name']] += float(category['total'])
        else:
            expense_categories_dict[category['name']] = float(category['total'])
    
    # Converter para o formato esperado pelo template
    data = [{'name': name, 'total': total} for name, total in expense_categories_dict.items()]
    
    cursor.close()
    conn.close()
    
    return jsonify(data)

@income_bp.route('/api/income/monthly')
@login_required
def api_monthly_income():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute('''
        SELECT SUM(amount) as total, MONTH(date) as month, YEAR(date) as year
        FROM income
        WHERE user_id = %s AND YEAR(date) = YEAR(CURRENT_DATE())
        GROUP BY YEAR(date), MONTH(date)
        ORDER BY year, month
    ''', (session['user_id'],))
    data = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return jsonify(data)

@investments_bp.route('/api/investments/by-type')
@login_required
def api_investments_by_type():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Prepare filters
    filters = ["i.user_id = %s"]
    params = [session['user_id']]
    
    # Filter by type
    type_id = request.args.get('type_id')
    if type_id and type_id.isdigit() and int(type_id) > 0:
        filters.append("i.type_id = %s")
        params.append(int(type_id))
    
    # Filter by start date
    start_date = request.args.get('start_date')
    if start_date:
        filters.append("i.date >= %s")
        params.append(start_date)
    
    # Filter by end date
    end_date = request.args.get('end_date')
    if end_date:
        filters.append("i.date <= %s")
        params.append(end_date)
    
    # Build the query with filters
    query = f'''
        SELECT t.name, SUM(i.amount) as total
        FROM investments i
        JOIN investment_types t ON i.type_id = t.id
        WHERE {' AND '.join(filters)}
        GROUP BY t.name
    '''
    
    try:
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error retrieving investments by type: {err}")
        data = []
    
    cursor.close()
    conn.close()
    
    return jsonify(data)

# Blueprint URLs
expenses_bp.url_prefix = '/expenses'
investments_bp.url_prefix = '/investments'
income_bp.url_prefix = '/income'
budgets_bp.url_prefix = '/budgets'
categories_bp.url_prefix = '/categories'
# Currency blueprint URL prefix removed

# Currency exchange rates routes removed
