import os
import streamlit as st
import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from stocknews import StockNews
from datetime import date, datetime, timedelta
from prophet import Prophet
from prophet.plot import plot_plotly
from plotly import graph_objects as go
from alpha_vantage.fundamentaldata import FundamentalData

# Set Streamlit page config for a light, clean look
st.set_page_config(
    page_title="Market Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject custom CSS for a modern light theme
st.markdown("""
    <style>
    .stApp {
        background-color: #f8fafc;
        color: #22223b;
    }
    section[data-testid="stSidebar"] {
        background-color: #e9ecef;
    }
    .st-emotion-cache-10trblm, .st-emotion-cache-1v0mbdj, .st-emotion-cache-1d391kg {
        color: #2a9d8f !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        background: #e9ecef;
        border-radius: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #2a9d8f;
        font-weight: bold;
    }
    .stTabs [aria-selected="true"] {
        background: #2a9d8f !important;
        color: #fff !important;
        border-radius: 8px 8px 0 0;
    }
    div[data-testid="stMetric"] {
        background-color: #e9ecef;
        border-radius: 8px;
        padding: 10px;
        color: #2a9d8f;
    }
    hr {
        border-top: 1px solid #2a9d8f;
    }
    </style>
""", unsafe_allow_html=True)

load_dotenv()

st.title("Market Dashboard")
ticker = st.text_input("Enter Stock Ticker")
n_years = st.slider("Data Range (years):", 1, 10)
today_date = date.today().strftime("%Y-%m-%d")
start_date = datetime.now() - timedelta(days=n_years * 365)

def load_data():
    with st.spinner("Loading data..."):
        data = yf.download(ticker, start=start_date, end=today_date)
        data.reset_index(inplace=True)
    return data

def plot_ticker_data(data):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data["Date"], y=data["Open"], name="Stock Open"))
    fig.add_trace(go.Scatter(x=data["Date"], y=data["Close"], name="Stock Close"))
    if "Adj Close" in data.columns:
        fig.add_trace(go.Scatter(x=data["Date"], y=data["Adj Close"], name="Adj. Close"))
    else:
        fig.add_trace(go.Scatter(x=data["Date"], y=data["Close"], name="Adj. Close (using Close)"))
    fig.layout.update(xaxis_rangeslider_visible=True)
    st.plotly_chart(fig)

def get_metrics(data_copy):
    annual_return = data_copy["% Change"].mean() * 252 * 100
    st_dev = np.std(data_copy["% Change"]) * np.sqrt(252)
    st.metric(label="Annual Return", value=f"{round(annual_return, 4)}%")
    st.metric(label="Standard Deviation", value=f"{round(st_dev, 4)}%")
    st.metric(label="Risk Adjusted Return", value=f"{round(annual_return/(st_dev*100), 4)}%")

def current():
    if not ticker:
        st.warning("Stock Ticker Empty", icon="⚠️")
        return
    data = load_data()
    if data.empty:
        st.error("Invalid Ticker", icon="🚨")
        return
    st.subheader("Time Series Chart")
    plot_ticker_data(data)
    st.subheader("Stock Analysis")
    data_copy = data.copy()
    price_col = "Adj Close" if "Adj Close" in data.columns else "Close"
    data_copy["% Change"] = data_copy[price_col] / data_copy[price_col].shift(1) - 1
    data_copy.dropna(inplace=True)
    st.write(data_copy)
    st.divider()
    get_metrics(data_copy)

@st.cache_resource
def get_balance_sheet(_fd):
    balance_sheet = _fd.get_balance_sheet_annual(ticker)[0]
    if balance_sheet.empty:
        st.error("Invalid Ticker", icon="🚨")
        return
    bs = balance_sheet.T[2:]
    bs.columns = list(balance_sheet.T.iloc[0])
    return bs

@st.cache_resource
def get_income_statement(_fd):
    income_statement = _fd.get_income_statement_annual(ticker)[0]
    if income_statement.empty:
        st.error("Invalid Ticker", icon="🚨")
        return
    ics = income_statement.T[2:]
    return ics

@st.cache_data
def get_cashflow_statement(_fd):
    cash_flow = _fd.get_cash_flow_annual(ticker)[0]
    if cash_flow.empty:
        st.error("Invalid Ticker", icon="🚨")
        return
    cf = cash_flow.T[2:]
    cf.columns = list(cash_flow.T.iloc[0])
    return cf

def fundamental():
    if not ticker:
        st.warning("Stock Ticker Empty", icon="⚠️")
        return
    key = os.getenv("ALPHAVANTAGE_KEY")
    fd = FundamentalData(key, output_format="pandas")
    if not fd:
        st.error("API Limit Exceeded", icon="🚨")
        return
    st.subheader("Balance Sheet")
    with st.spinner("Loading data..."):
        bs = get_balance_sheet(fd)
        st.write(bs)
    st.subheader("Income Statement")
    with st.spinner("Loading data..."):
        ics = get_income_statement(fd)
        st.write(ics)
    st.subheader("Cash Flow Statement")
    with st.spinner("Loading data..."):
        cf = get_cashflow_statement(fd)
        st.write(cf)

def train_model(model, df_train):
    model.fit(df_train)
    future = model.make_future_dataframe(periods=n_years*365)
    forecast = model.predict(future)
    return forecast

def plot_forecast_data(model, data):
    st.subheader("Forecast Chart")
    fig1 = plot_plotly(model, data)
    fig1.layout.update(width=700, xaxis_rangeslider_visible=True)
    st.plotly_chart(fig1)
    st.subheader("Forecast Components")
    fig2 = model.plot_components(data)
    st.write(fig2)

def forecast():
    if not ticker:
        st.warning("Stock Ticker Empty", icon="⚠️")
        return
    data = load_data()
    if data.empty:
        st.error("Invalid Ticker", icon="🚨")
        return

    price_col = None
    if "Close" in data.columns:
        price_col = "Close"
    elif "Adj Close" in data.columns:
        price_col = "Adj Close"

    if price_col is None or "Date" not in data.columns:
        st.error("Data does not contain required columns for forecasting.", icon="🚨")
        st.write("Available columns:", data.columns)
        return

    df_train = data[["Date", price_col]].copy()
    df_train = df_train.rename(columns={"Date": "ds", price_col: "y"})

    missing_cols = [col for col in ["ds", "y"] if col not in df_train.columns]
    if missing_cols:
        st.error(f"Missing columns after renaming: {missing_cols}", icon="🚨")
        st.write(df_train.head())
        return

    df_train = df_train.dropna(subset=["ds", "y"])
    df_train["y"] = pd.to_numeric(df_train["y"], errors="coerce")
    df_train = df_train.dropna(subset=["y"])

    if df_train.empty:
        st.error("Prepared data for Prophet is empty after cleaning.", icon="🚨")
        st.write(df_train.head())
        return

    model = Prophet()
    with st.spinner("Loading data..."):
        forecast_data = train_model(model, df_train)
    plot_forecast_data(model, forecast_data)
    st.subheader("Forecast Analysis")
    st.write(forecast_data)

def news():
    if not ticker:
        st.warning("Stock Ticker Empty", icon="⚠️")
        return
    st.header(f"{ticker} News")
    with st.spinner("Loading data..."):
        sn = StockNews(ticker, save_news=False)
        df_news = sn.read_rss()
    for i in range(min(10, len(df_news))):
        st.divider()
        st.subheader(f"**{df_news['title'][i]}**")
        st.markdown(f"_**Published:**_ {df_news['published'][i]}")
        st.markdown(f"_{df_news['summary'][i]}_")
        ttl_sentiment = df_news["sentiment_title"][i]
        body_sentiment = df_news["sentiment_summary"][i]
        st.markdown(
            f"_**Sentiment:**_ :green[title={ttl_sentiment}, body={body_sentiment}]")

tab1, tab2, tab3, tab4 = st.tabs(
    ["Stock Overview", "Stock Forecast", "Accounting Data", "Market News"])
with tab1:
    current()
with tab2:
    forecast()
with tab3:
    fundamental()
with tab4:
    news()