from datetime import datetime, timedelta
import mysql.connector
import dbcreate

def get_db_connection():
    """Establish and return a database connection"""
    connection = mysql.connector.connect(
        host=dbcreate.DB_HOST,
        port=dbcreate.DB_PORT,
        user=dbcreate.DB_USER,
        password=dbcreate.DB_PASSWORD,
        database=dbcreate.DB_NAME
    )
    return connection

def check_and_transfer_previous_month_balance(user_id):
    """
    Check if the month has changed since the last check and transfer the previous month's balance
    as a new income entry if it has.
    
    Args:
        user_id: The ID of the user to check and transfer balance for
    
    Returns:
        bool: True if a transfer was made, False otherwise
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get the current date and the first day of the current month
        current_date = datetime.now().date()
        first_day_current_month = datetime(current_date.year, current_date.month, 1).date()
        
        print(f"[MONTH_TRANSITION] Verificando transição de mês para usuário {user_id} na data {current_date}")
        
        # Check if we've already processed this month transition for this user
        cursor.execute(
            """
            SELECT * FROM income 
            WHERE user_id = %s 
            AND description = 'Saldo mês anterior' 
            AND MONTH(date) = %s 
            AND YEAR(date) = %s
            """, 
            (user_id, current_date.month, current_date.year)
        )
        
        existing_transfer = cursor.fetchone()
        
        if existing_transfer:
            # We've already processed this month's transition
            print(f"[MONTH_TRANSITION] Já existe uma transferência para o mês atual: ID={existing_transfer['id']}, Valor={existing_transfer['amount']}")
            return False
        
        # Calculate the previous month and year
        if current_date.month == 1:
            previous_month = 12
            previous_year = current_date.year - 1
        else:
            previous_month = current_date.month - 1
            previous_year = current_date.year
        
        print(f"[MONTH_TRANSITION] Calculando saldo do mês anterior: {previous_month}/{previous_year}")
        
        # Get the total income from the previous month
        cursor.execute(
            """
            SELECT SUM(amount) as total 
            FROM income 
            WHERE user_id = %s 
            AND MONTH(date) = %s 
            AND YEAR(date) = %s
            """, 
            (user_id, previous_month, previous_year)
        )
        
        income_result = cursor.fetchone()
        total_income = float(income_result['total']) if income_result and income_result['total'] else 0
        print(f"[MONTH_TRANSITION] Total de receitas do mês anterior: R$ {total_income:.2f}")
        
        # Get the total expenses from the previous month (regular expenses)
        cursor.execute(
            """
            SELECT SUM(amount) as total 
            FROM expenses 
            WHERE user_id = %s 
            AND MONTH(date) = %s 
            AND YEAR(date) = %s
            AND (is_recurring = FALSE OR is_recurring IS NULL)
            AND (is_installment = FALSE OR is_installment IS NULL)
            """, 
            (user_id, previous_month, previous_year)
        )
        
        regular_expenses_result = cursor.fetchone()
        total_regular_expenses = float(regular_expenses_result['total']) if regular_expenses_result and regular_expenses_result['total'] else 0
        print(f"[MONTH_TRANSITION] Total de despesas regulares do mês anterior: R$ {total_regular_expenses:.2f}")
        
        # Get recurring expenses for the previous month
        cursor.execute(
            """
            SELECT SUM(amount) as total
            FROM expenses
            WHERE user_id = %s 
            AND is_recurring = TRUE
            AND (
                (date <= LAST_DAY(%s) AND (recurring_end_date IS NULL OR recurring_end_date >= %s))
                OR
                (MONTH(date) = %s AND YEAR(date) = %s)
            )
            AND (
                (recurring_type = 'monthly') OR
                (recurring_type = 'yearly' AND MONTH(date) = %s) OR
                (recurring_type = 'weekly')
            )
            """, 
            (user_id, 
             f"{previous_year}-{previous_month:02d}-01", 
             f"{previous_year}-{previous_month:02d}-01",
             previous_month, 
             previous_year,
             previous_month)
        )
        
        recurring_expenses_result = cursor.fetchone()
        total_recurring_expenses = float(recurring_expenses_result['total']) if recurring_expenses_result and recurring_expenses_result['total'] else 0
        print(f"[MONTH_TRANSITION] Total de despesas recorrentes do mês anterior: R$ {total_recurring_expenses:.2f}")
        
        # Get installment expenses for the previous month
        cursor.execute(
            """
            SELECT id, amount, date, total_installments, description
            FROM expenses
            WHERE user_id = %s AND is_installment = TRUE
            """, 
            (user_id,)
        )
        
        installment_expenses = cursor.fetchall()
        total_installment_expenses = 0
        
        print(f"[MONTH_TRANSITION] Processando {len(installment_expenses)} despesas parceladas")
        
        # Calculate the installment expenses for the previous month
        for expense in installment_expenses:
            expense_date = expense['date']
            total_installments = expense['total_installments']
            expense_amount = expense['amount']
            installment_amount = expense_amount / total_installments
            
            print(f"[MONTH_TRANSITION] Analisando despesa parcelada: {expense['description']}, Valor: {expense_amount}, Parcelas: {total_installments}")
            
            # Generate all installment dates
            for i in range(total_installments):
                month_offset = i
                installment_year = expense_date.year + ((expense_date.month - 1 + month_offset) // 12)
                installment_month = ((expense_date.month - 1 + month_offset) % 12) + 1
                
                # If this installment falls in the previous month, add it to the total
                if installment_month == previous_month and installment_year == previous_year:
                    total_installment_expenses += installment_amount
                    print(f"[MONTH_TRANSITION] Parcela {i+1}/{total_installments} cai no mês anterior: R$ {installment_amount:.2f}")
        
        print(f"[MONTH_TRANSITION] Total de despesas parceladas do mês anterior: R$ {total_installment_expenses:.2f}")
        
        # Calculate the total expenses for the previous month - garantindo que todos sejam float
        total_regular_expenses = float(total_regular_expenses)
        total_recurring_expenses = float(total_recurring_expenses)
        total_installment_expenses = float(total_installment_expenses)
        
        total_expenses = total_regular_expenses + total_recurring_expenses + total_installment_expenses
        
        # Calculate the balance (income - expenses)
        previous_month_balance = float(total_income) - float(total_expenses)
        
        print(f"[MONTH_TRANSITION] Saldo do mês anterior: R$ {previous_month_balance:.2f}")
        
        # Check if we've already processed a negative balance for this month
        if previous_month_balance < 0:
            cursor.execute(
                """
                SELECT * FROM expenses 
                WHERE user_id = %s 
                AND description = 'Saldo negativo mês anterior' 
                AND MONTH(date) = %s 
                AND YEAR(date) = %s
                """, 
                (user_id, current_date.month, current_date.year)
            )
            
            existing_negative_transfer = cursor.fetchone()
            
            if existing_negative_transfer:
                print(f"[MONTH_TRANSITION] Já existe uma transferência de saldo negativo para o mês atual: ID={existing_negative_transfer['id']}, Valor={existing_negative_transfer['amount']}")
                return False
        
        # Create a new income entry if the balance is positive
        if previous_month_balance > 0:
            print(f"[MONTH_TRANSITION] Criando nova entrada de receita com o saldo do mês anterior: R$ {previous_month_balance:.2f}")
            
            # Create a new income entry for the current month with the previous month's balance
            cursor.execute(
                """
                INSERT INTO income 
                (user_id, source_id, amount, description, date) 
                VALUES (%s, 
                        (SELECT id FROM income_sources WHERE name = 'Outros' LIMIT 1), 
                        %s, 
                        'Saldo m\u00eas anterior', 
                        %s)
                """, 
                (user_id, previous_month_balance, first_day_current_month)
            )
            
            conn.commit()
            print(f"[MONTH_TRANSITION] Transferência de saldo positivo concluída com sucesso!")
            return True
        
        # Create a new expense entry if the balance is negative
        elif previous_month_balance < 0:
            # Convert to positive value for the expense entry
            negative_balance_amount = abs(previous_month_balance)
            print(f"[MONTH_TRANSITION] Criando nova entrada de despesa com o saldo negativo do mês anterior: R$ {negative_balance_amount:.2f}")
            
            # Get the 'Outros' expense category ID
            cursor.execute(
                """
                SELECT id FROM expense_categories 
                WHERE name = 'Outros' AND (user_id = %s OR user_id IS NULL) 
                LIMIT 1
                """, 
                (user_id,)
            )
            
            category_result = cursor.fetchone()
            if not category_result:
                print(f"[MONTH_TRANSITION] Categoria 'Outros' não encontrada. Criando categoria...")
                cursor.execute(
                    """
                    INSERT INTO expense_categories (user_id, name, description)
                    VALUES (%s, 'Outros', 'Categoria para despesas diversas')
                    """,
                    (user_id,)
                )
                conn.commit()
                category_id = cursor.lastrowid
            else:
                category_id = category_result['id']
            
            # Create a new expense entry for the current month with the negative balance
            cursor.execute(
                """
                INSERT INTO expenses 
                (user_id, category_id, amount, description, date) 
                VALUES (%s, %s, %s, 'Saldo negativo mês anterior', %s)
                """, 
                (user_id, category_id, negative_balance_amount, first_day_current_month)
            )
            
            conn.commit()
            print(f"[MONTH_TRANSITION] Transferência de saldo negativo concluída com sucesso!")
            return True
        
        else:  # Balance is exactly zero
            print(f"[MONTH_TRANSITION] Saldo do mês anterior é exatamente zero. Nenhuma transferência será feita.")
            return False
    
    except Exception as e:
        print(f"[MONTH_TRANSITION] Erro na transferência de saldo: {e}")
        return False
    
    finally:
        cursor.close()
        conn.close()
