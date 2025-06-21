# Sistema de Controle de Gastos e Investimentos

Um sistema web completo para gerenciar suas finanças pessoais, controlar despesas, receitas e investimentos.

## Funcionalidades

- Cadastro e autenticação de usuários
- Gerenciamento de despesas por categorias
- Controle de receitas por fontes
- Acompanhamento de investimentos por tipos e níveis de risco
- Definição de orçamentos por categoria
- Dashboards com gráficos e estatísticas
- Relatórios de gastos e investimentos

## Requisitos

- Python 3.8+
- MySQL 5.7+ ou MariaDB 10.3+
- Pip (gerenciador de pacotes Python)

## Instalação

1. Clone este repositório ou baixe os arquivos

2. Instale as dependências:
```
pip install -r requirements.txt
```

3. Configure o banco de dados:
   - Crie um arquivo `.env` na raiz do projeto e preencha as variáveis:
   ```
   DB_HOST=127.0.0.1
   DB_PORT=3306
   DB_USER=acore
   DB_PASSWORD=acore
   DB_NAME=expense_tracker
   ```

4. Execute o script de criação do banco de dados (opcional, apenas na primeira vez):
```
python dbcreate.py
```

5. Inicie a aplicação:
```
python app.py
```

6. Acesse a aplicação no navegador:
```
http://localhost:5000
```

## Estrutura do Projeto

- `app.py` - Arquivo principal da aplicação Flask
- `dbcreate.py` - Script para criação e configuração do banco de dados
- `routes.py` - Rotas e controladores da aplicação
- `templates/` - Arquivos HTML da interface
- `static/` - Arquivos CSS, JavaScript e imagens

## Uso

1. Registre-se na aplicação com seu nome, e-mail e senha
2. Faça login para acessar o dashboard
3. Utilize o menu de navegação para acessar as diferentes seções:
   - Dashboard - Visão geral das finanças
   - Despesas - Gerenciamento de gastos
   - Receitas - Controle de entradas
   - Investimentos - Acompanhamento de aplicações
   - Orçamentos - Definição de limites de gastos
   - Categorias - Gerenciamento de categorias, tipos e fontes

## Personalização

Você pode personalizar o sistema editando:
- Categorias de despesas
- Tipos de investimentos
- Fontes de receitas

## Segurança

- As senhas são armazenadas com hash seguro
- Autenticação é necessária para acessar todas as páginas do sistema
- Cada usuário tem acesso apenas aos seus próprios dados

## Suporte

Para problemas ou dúvidas, abra uma issue no repositório ou entre em contato com o desenvolvedor.
