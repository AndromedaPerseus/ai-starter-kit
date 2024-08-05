import os
import sys
from typing import List, Tuple

import streamlit

current_dir = os.path.dirname(os.path.abspath(__file__))
kit_dir = os.path.abspath(os.path.join(current_dir, '..'))
repo_dir = os.path.abspath(os.path.join(kit_dir, '..'))

sys.path.append(kit_dir)
sys.path.append(repo_dir)

from financial_insights.streamlit.utilities_app import save_output_callback
from financial_insights.streamlit.utilities_methods import handle_userinput, set_fc_llm


def get_yfinance_news() -> None:
    streamlit.markdown('<h2> Financial News Scraping </h2>', unsafe_allow_html=True)
    streamlit.markdown(
        '<a href="https://uk.finance.yahoo.com/" target="_blank" '
        'style="color:cornflowerblue;text-decoration:underline;"><h3>via Yahoo! Finance News</h3></a>',
        unsafe_allow_html=True,
    )
    output = streamlit.empty()

    user_request = streamlit.text_input(
        'Enter the yfinance news that you want to retrieve for given companies',
        key='yahoo_news',
    )

    # Retrieve news
    if streamlit.button('Retrieve News'):
        with streamlit.expander('**Execution scratchpad**', expanded=True):
            if user_request is not None:
                answer, url_list = handle_yfinance_news(user_request)
            else:
                raise ValueError('No input provided')

        if answer is not None:
            content = user_request + '\n\n' + answer + '\n\n' + '\n'.join(url_list) + '\n\n\n'
            if streamlit.button(
                'Save Answer',
                on_click=save_output_callback,
                args=(content, 'yfinance_news.txt'),
            ):
                pass


def handle_yfinance_news(user_question: str) -> Tuple[str, List[str]]:
    """
    Handle user input and generate a response, also update chat UI in streamlit app

    Args:
    user_request (str): The user's question or input.
    """
    streamlit.session_state.tools = [
        'retrieve_symbol_list',
        'scrape_yahoo_finance_news',
    ]
    set_fc_llm(
        tools=streamlit.session_state.tools,
        default_tool=None,
    )
    user_request = (
        'You are an expert in the stock market. Please answer the following question.\n'
        + user_question
        + 'Company names should be expressed via their ticker symbols.'
    )

    response = handle_userinput(user_question, user_request)

    assert (
        isinstance(response, tuple)
        and len(response) == 2
        and isinstance(response[0], str)
        and isinstance(response[1], list)
        and all(isinstance(item, str) for item in response[1])
    ), f'Invalid response: {response}'

    return response
