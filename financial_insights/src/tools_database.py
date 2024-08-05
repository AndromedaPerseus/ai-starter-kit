import datetime
import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Union

import pandas
import streamlit
import yfinance
from dotenv import load_dotenv
from langchain.output_parsers import PydanticOutputParser
from langchain.prompts import PromptTemplate
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_community.utilities import SQLDatabase
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from pandasai import SmartDataframe
from pandasai.connectors import SqliteConnector
from sqlalchemy import Inspector, create_engine

current_dir = os.path.dirname(os.path.abspath(__file__))
kit_dir = os.path.abspath(os.path.join(current_dir, '..'))
repo_dir = os.path.abspath(os.path.join(kit_dir, '..'))
sys.path.append(kit_dir)
sys.path.append(repo_dir)


CONFIG_PATH = os.path.join(kit_dir, 'config.yaml')

TEMP_DIR = 'financial_insights/streamlit/cache/'

load_dotenv(os.path.join(repo_dir, '.env'))

DB_PATH = 'financial_insights/streamlit/cache/sources/stock_database.db'


class DatabaseSchema(BaseModel):
    """Create a SQL database for a list of stocks/companies."""

    symbol_list: List[str] = Field('List of stock ticker symbols.')
    start_date: datetime.date = Field('Start date.')
    end_date: datetime.date = Field('End date.')


@tool(args_schema=DatabaseSchema)
def create_stock_database(
    symbol_list: List[str] = list(),
    start_date: datetime.date = datetime.datetime.today().date() - datetime.timedelta(days=365),
    end_date: datetime.date = datetime.datetime.today().date(),
) -> Dict[str, List[str]]:
    """Create a SQL database for a list of stocks/companies."""
    # Check dates
    if start_date > end_date or (end_date - datetime.timedelta(days=365)) < start_date:
        raise ValueError('Start date must be before the end date.')

    company_data_dict = dict()
    for symbol in symbol_list:
        company_data_dict[symbol] = extract_yfinance_data(symbol, start_date, end_date)

    company_tables = store_company_dataframes_to_sqlite(db_name=DB_PATH, company_data_dict=company_data_dict)

    return company_tables


def extract_yfinance_data(
    symbol: str, start_date: datetime.date, end_date: datetime.date
) -> Dict[str, Union[pandas.DataFrame, Dict[Any, Any]]]:
    company = yfinance.Ticker(ticker=symbol)

    company_dict = dict()

    # get all stock info
    company_dict['info'] = company.info

    # get historical market data
    company_dict['history'] = hist = company.history(start=start_date, end=end_date)

    # show meta information about the history (requires history() to be called first)
    company_dict['history_metadata'] = company.history_metadata

    # show actions (dividends, splits, capital gains)
    company_dict['actions'] = company.actions
    company_dict['dividends'] = company.dividends
    company_dict['splits'] = company.splits
    company_dict['capital_gains'] = company.capital_gains  # only for mutual funds & etfs

    # show share count
    company_dict['shares'] = company.get_shares_full(start=start_date, end=end_date)

    # show financials:
    # - income statement
    company_dict['income_stmt'] = convert_date_index_to_column(company.income_stmt.T)
    company_dict['quarterly_income_stmt'] = convert_date_index_to_column(company.quarterly_income_stmt.T)
    # - balance sheet
    company_dict['balance_sheet'] = convert_date_index_to_column(company.balance_sheet.T)
    company_dict['quarterly_balance_sheet'] = convert_date_index_to_column(company.quarterly_balance_sheet.T)
    # - cash flow statement
    company_dict['cashflow'] = convert_date_index_to_column(company.cashflow.T)
    company_dict['quarterly_cashflow'] = convert_date_index_to_column(company.quarterly_cashflow.T)
    # see `Ticker.get_income_stmt()` for more options

    # show holders
    company_dict['major_holders'] = company.major_holders
    company_dict['institutional_holders'] = company.institutional_holders
    company_dict['mutualfund_holders'] = company.mutualfund_holders
    company_dict['insider_transactions'] = company.insider_transactions
    company_dict['insider_purchases'] = company.insider_purchases
    company_dict['insider_roster_holders'] = company.insider_roster_holders

    company_dict['sustainability'] = company.sustainability

    # show recommendations
    company_dict['recommendations'] = company.recommendations
    company_dict['recommendations_summary'] = company.recommendations_summary
    company_dict['upgrades_downgrades'] = company.upgrades_downgrades

    # Show future and historic earnings dates, returns at most next 4 quarters and last 8 quarters by default.
    # Note: If more are needed use company.get_earnings_dates(limit=XX) with increased limit argument.
    company_dict['earnings_dates'] = company.earnings_dates

    # show ISIN code - *experimental*
    # ISIN = International Securities Identification Number
    company_dict['isin'] = company.isin

    # show options expirations
    company_dict['options'] = company.options

    # show news
    company_dict['news'] = company.news

    # # get option chain for specific expiration
    # company_dict["option_chain"] = company.option_chain()
    # # data available via: opt.calls, opt.puts

    return company_dict


def store_company_dataframes_to_sqlite(
    db_name: str, company_data_dict: Dict[str, Union[pandas.DataFrame, Dict[Any, Any]]]
) -> Dict[str, list[str]]:
    """
    Stores multiple dataframes for each company into an SQLite database.

    :param db_name: The name of the SQLite database file.
    :param company_data_dict: Dictionary where the key is the company name,
        and the value is another dictionary containing
        dataframes with their corresponding purpose/type.
    """
    # # Connect to the SQLite database
    # conn = sqlite3.connect(db_name)

    engine = create_engine(f'sqlite:///{DB_PATH}')

    # Create a dictionary with company names as keys and SQL tables as values
    company_tables: Dict[str, list[str]] = dict()

    # Process each company
    for company, company_data in company_data_dict.items():
        # Make sure company name is SQLite-friendly
        company_base_name = company.replace(' ', '_').lower()
        company_tables[company] = list()

        for df_name, data in company_data.items():
            # Build a table name using company name and dataframe purpose/type
            table_name = f'{company_base_name}_{df_name}'
            if isinstance(data, pandas.DataFrame):
                df = data
            elif isinstance(data, dict):
                df = pandas.DataFrame.from_dict(data, orient='index', columns=['Value'])
            elif isinstance(data, pandas.Series):
                df = data.to_frame()
            elif isinstance(data, str):
                df = pandas.DataFrame({df_name: [data]})
            elif isinstance(data, (list, tuple)):
                df = pandas.DataFrame({df_name: data})
            else:
                raise ValueError(f'Unsupported data type for {df_name} of {company}: {type(data)}')

            # Make sure column names are SQLite-friendly
            for column in df.columns:
                df = df.rename({column: f'{column}'.replace(' ', '_')}, axis='columns')

            # Convert list-type and dict-type entries to JSON strings
            df = df.applymap(lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x)

            # df.to_sql(table_name, conn, if_exists="replace", index=False)
            df.to_sql(table_name, engine, if_exists='replace', index=False)
            logging.info(f"DataFrame '{df_name}' for {company} stored in table '{table_name}'.")

            # Populated company tables list with table name
            company_tables[company].append(table_name)

    return company_tables


class QueryDatabaseSchema(BaseModel):
    """Query a SQL database for a list of stocks/companies."""

    user_request: str = Field('Query to be performed on the database')
    symbol_list: List[str] = Field('List of stock ticker symbols.')
    method: str = Field('Method to be used in query. Either "text-to-SQL" or "PandasAI-SqliteConnector"')


@tool(args_schema=QueryDatabaseSchema)
def query_stock_database(
    user_request: str, symbol_list: List[str], method: str
) -> Union[Any, Dict[str, str | List[str]]]:
    """Query a SQL database for a list of stocks/companies."""

    assert method in [
        'text-to-SQL',
        'PandasAI-SqliteConnector',
    ], f'Invalid method {method}'
    assert isinstance(symbol_list, list), 'Symbol List must be a list of strings.'
    assert len(symbol_list) > 0, 'Symbol List must contain at least one symbol: please specify the company to query.'

    if method == 'text-to-SQL':
        return query_stock_database_sql(user_request, symbol_list)
    elif method == 'PandasAI-SqliteConnector':
        return query_stock_database_pandasai(user_request, symbol_list)
    else:
        raise Exception('Invalid method')


def query_stock_database_sql(user_request: str, symbol_list: List[str]) -> Dict[str, str | List[str]]:
    prompt = PromptTemplate.from_template(
        """<|begin_of_text|><|start_header_id|>system<|end_header_id|> 
        
        {selected_schemas}
        
        Generate a query using valid SQLite to answer the following questions 
        for the summarized tables schemas provided above.
        Do not assume the values on the database tables before generating the SQL query, 
        always generate a SQL that query what is asked. 
        The query must be in the format: ```sql\nquery\n```
        
        Example:
        
        ```sql
        SELECT * FROM mainTable;
        ```
        
        <|eot_id|><|start_header_id|>user<|end_header_id|>\
            
        {input}
        <|eot_id|><|start_header_id|>assistant<|end_header_id|>"""
    )

    # Chain that receives the natural language input and the table schema, then pass the teh formatted prompt to the llm
    # and finally execute the sql finder method, retrieving only the filtered SQL query
    query_generation_chain = prompt | streamlit.session_state.fc.llm | RunnableLambda(sql_finder)

    selected_tables = select_database_tables(user_request, symbol_list)
    selected_schemas = get_table_summaries_from_names(selected_tables)

    query: str = query_generation_chain.invoke({'selected_schemas': selected_schemas, 'input': user_request})

    queries = query.split(';')
    queries = [query for query in queries if len(query) > 0]

    engine = create_engine(f'sqlite:///{DB_PATH}')
    db = SQLDatabase(engine=engine, include_tables=selected_tables)
    query_executor = QuerySQLDataBaseTool(db=db)

    results = []
    for query in queries:
        if len(query) > 0:
            results.append(query_executor.invoke(query))

    message = '\n'.join([f'Query {query} executed with result {result}' for query, result in zip(queries, results)])

    response_dict: Dict[str, str | List[str]] = dict()
    response_dict['queries'] = queries
    response_dict['results'] = results
    response_dict['message'] = message
    return response_dict


def sql_finder(text: str) -> Any:
    """Search in a string for a SQL query or code with format"""

    # regex for finding sql_code_pattern with format:
    # ```sql
    #    <query>
    # ```
    sql_code_pattern = re.compile(r'```sql\s+(.*?)\s+```', re.DOTALL)
    match = sql_code_pattern.search(text)
    if match is not None:
        query = match.group(1)
        return query
    else:
        # regex for finding sql_code_pattern with format:
        # ```
        # <quey>
        # ```
        code_pattern = re.compile(r'```\s+(.*?)\s+```', re.DOTALL)
        match = code_pattern.search(text)
        if match is not None:
            query = match.group(1)
            return query
        else:
            raise Exception('No SQL code found in LLM generation')


def query_stock_database_pandasai(user_request: str, symbol_list: List[str]) -> Any:
    """Query a SQL database for a list of stocks/companies."""

    response = dict()
    for symbol in symbol_list:
        selected_tables = select_database_tables(user_request, [symbol])

        response[symbol] = list()
        for table in selected_tables:
            # selecteed_tables = select_database_tables(user_request, symbol_list)
            connector = SqliteConnector(
                config={
                    'database': DB_PATH,
                    'table': table,
                }
            )

            df = SmartDataframe(
                connector,
                config={
                    'llm': streamlit.session_state.fc.llm,
                    'open_charts': False,
                    'save_charts': True,
                    'save_charts_path': TEMP_DIR + '/db_query/',
                },
            )
            response[symbol].append(df.chat(user_request))

    return response


def convert_date_index_to_column(df: pandas.DataFrame) -> pandas.DataFrame:
    df_new = df.reset_index()
    new_column_list = ['Date'] + list(df.columns)
    df_new.columns = new_column_list
    return df_new


class TableName(BaseModel):
    table_names: List[str] = Field(description='List of the most relevant table names.')


def select_database_tables(user_request: str, symbol_list: List[str]) -> List[str]:
    summary_text = get_table_summaries_from_symbols(symbol_list)

    parser = PydanticOutputParser(pydantic_object=TableName)
    prompt_template = (
        'Consider the following table summaries:\n{summary_text}\n'
        'Which are the most relevant tables to the following query.\n'
        '"{user_request}"?\n'
        '{format_instructions}'
    )

    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=['user_request', 'summary_text'],
        partial_variables={'format_instructions': parser.get_format_instructions()},
    )

    chain = prompt | streamlit.session_state.fc.llm | parser

    # Get response from llama3
    response = chain.invoke({'user_request': user_request, 'summary_text': summary_text})
    return response.table_names


def get_table_summaries_from_symbols(symbol_list: List[str]) -> str:
    """Get a list of available SQL tables."""
    inspector = Inspector.from_engine(create_engine('sqlite:///' + DB_PATH))
    tables_names = inspector.get_table_names()

    table_summaries = {}
    for table in tables_names:
        # Extract the first word from the name string to get the symbol
        table_symbol = table.split('_')[0]

        # Check if the symbol is in the list of symbols to be queried
        if table_symbol not in [symbol.lower() for symbol in symbol_list]:
            continue

        columns = inspector.get_columns(table)
        column_names = [col['name'] for col in columns]

        # Summarize the content of the table based on its column names
        table_summaries[table] = ', '.join(column_names)

    summary_text = json.dumps(table_summaries)
    return summary_text


def get_table_summaries_from_names(table_names: List[str]) -> str:
    """Get a list of available SQL tables."""
    inspector = Inspector.from_engine(create_engine('sqlite:///' + DB_PATH))
    inspected_tables_names = inspector.get_table_names()
    inspected_tables_names_symbols = [
        inspected_table.split('_')[0].lower() for inspected_table in inspected_tables_names
    ]

    table_summaries = {}
    for table in table_names:
        # Extract the first word from the name string to get the symbol
        table_symbol = table.split('_')[0].lower()

        # Check if the symbol is in the list of symbols to be queried
        if table_symbol not in [symbol.lower() for symbol in inspected_tables_names_symbols]:
            continue

        columns = inspector.get_columns(table)
        column_names = [col['name'] for col in columns]

        # Summarize the content of the table based on its column names
        table_summaries[table] = ', '.join(column_names)

    summary_text = json.dumps(table_summaries)
    return summary_text
