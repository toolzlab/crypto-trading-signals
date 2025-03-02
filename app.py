# app.py
import streamlit as st
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, timedelta
import os
import sys

# Add the parent directory to sys.path to import from our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our modules
import config
from binance_client import BinanceClient
from signal_generator import SignalGenerator
from analyzers import fair_value_gaps, liquidity, change_in_state, smt, order_blocks, po3

# Initialize Binance client
client = BinanceClient()
generator = SignalGenerator(client)

# Set page config
st.set_page_config(
    page_title="Crypto Trading Signals Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        border-radius: 4px;
        background-color: #f0f2f6;
        padding: 10px 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #4CAF50;
        color: white;
    }
    .metrics-container {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
    }
    .metrics-card {
        background-color: white;
        border-radius: 5px;
        padding: 16px;
        flex: 1;
        min-width: 200px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# Sidebar
st.sidebar.title("Trading System Settings")

# Risk management settings
st.sidebar.header("Risk Management")
account_size = st.sidebar.number_input("Account Size ($)", min_value=10.0, value=float(config.ACCOUNT_SIZE), step=10.0)
risk_per_trade = st.sidebar.number_input("Risk Per Trade ($)", min_value=1.0, value=float(config.RISK_PER_TRADE), max_value=account_size, step=1.0)
leverage = st.sidebar.number_input("Leverage", min_value=1, value=int(config.LEVERAGE), step=1)

# Signal settings
st.sidebar.header("Signal Settings")
max_signals_per_pair = st.sidebar.slider("Max Signals Per Pair", 1, 5, 1, help="Maximum number of signals to show per trading pair")

# Timeframe settings
st.sidebar.header("Timeframes")
selected_timeframes = st.sidebar.multiselect(
    "Select Timeframes",
    ["4h", "1h", "15m", "5m", "1m"],
    default=["4h", "1h", "15m"]
)

# Trading pairs settings
st.sidebar.header("Trading Pairs")
selected_pairs = st.sidebar.multiselect(
    "Select Trading Pairs",
    config.PRIMARY_PAIRS,
    default=config.PRIMARY_PAIRS[:3]  # Default to first 3 pairs
)

# Auto refresh settings
st.sidebar.header("Auto Refresh")
auto_refresh = st.sidebar.checkbox("Enable Auto Refresh", value=True)
refresh_interval = st.sidebar.slider("Refresh Interval (minutes)", min_value=1, max_value=60, value=5)

# Function to load signals from file
@st.cache_data(ttl=60)  # Cache data for 60 seconds
def load_signals():
    try:
        if os.path.exists("signals.json"):
            with open("signals.json", "r") as f:
                data = json.load(f)
                return data
        return {"generated_at": None, "signals": {}}
    except Exception as e:
        st.error(f"Error loading signals: {e}")
        return {"generated_at": None, "signals": {}}

# Function to generate new signals
def generate_new_signals():
    # Update config values with sidebar inputs
    config.ACCOUNT_SIZE = account_size
    config.RISK_PER_TRADE = risk_per_trade
    config.LEVERAGE = leverage
    
    all_signals = {}
    
    with st.spinner("Generating trading signals..."):
        for symbol in selected_pairs:
            try:
                # Pass the max_signals_per_pair parameter
                symbol_signals = generator.generate_signals(symbol, max_signals_per_pair)
                if symbol_signals:
                    all_signals[symbol] = symbol_signals
            except Exception as e:
                st.error(f"Error generating signals for {symbol}: {e}")
    
    return all_signals

# Function to format datetime
def format_datetime(dt_str):
    if isinstance(dt_str, str):
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    else:
        dt = dt_str
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# Function to plot candlestick chart with signals
def plot_candlestick_chart(symbol, timeframe, signals=None):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    
    candles = client.get_candles(symbol, timeframe, limit=100)
    if candles is None or len(candles) == 0:
        st.warning(f"No candle data available for {symbol} on {timeframe} timeframe")
        return None
    
    # Create figure with secondary y-axis for volume
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.02, row_heights=[0.8, 0.2])
    
    # Add candlestick chart
    fig.add_trace(go.Candlestick(
        x=candles.index,
        open=candles['open'],
        high=candles['high'],
        low=candles['low'],
        close=candles['close'],
        name='Price'
    ), row=1, col=1)
    
    # Add volume bar chart
    colors = ['red' if candles['close'].iloc[i] < candles['open'].iloc[i] else 'green' 
              for i in range(len(candles))]
    
    fig.add_trace(go.Bar(
        x=candles.index,
        y=candles['volume'],
        marker_color=colors,
        name='Volume'
    ), row=2, col=1)
    
    # Add signals if available
    if signals:
        for signal in signals:
            # Convert timestamp to datetime if it's a string
            if isinstance(signal.get('generated_at'), str):
                signal_time = datetime.fromisoformat(signal['generated_at'].replace('Z', '+00:00'))
            else:
                signal_time = signal.get('generated_at')
            
            # Find closest candle to signal time
            if signal_time is not None:
                closest_time = min(candles.index, key=lambda x: abs(x - signal_time))
                
                # Add entry marker
                marker_symbol = 'triangle-up' if signal['type'] == 'long' else 'triangle-down'
                marker_color = 'green' if signal['type'] == 'long' else 'red'
                
                fig.add_trace(go.Scatter(
                    x=[closest_time], 
                    y=[signal['entry']],
                    mode='markers',
                    marker=dict(symbol=marker_symbol, size=12, color=marker_color),
                    name=f"{signal['type'].capitalize()} Entry"
                ), row=1, col=1)
                
                # Add stop loss and target lines
                fig.add_trace(go.Scatter(
                    x=[closest_time, candles.index[-1]],
                    y=[signal['stop'], signal['stop']],
                    mode='lines',
                    line=dict(dash='dash', color='red', width=1),
                    name='Stop Loss'
                ), row=1, col=1)
                
                fig.add_trace(go.Scatter(
                    x=[closest_time, candles.index[-1]],
                    y=[signal['target'], signal['target']],
                    mode='lines',
                    line=dict(dash='dash', color='blue', width=1),
                    name='Target'
                ), row=1, col=1)
    
    # Add fair value gaps
    fvgs = fair_value_gaps.detect_fair_value_gaps(candles)
    for fvg in fvgs:
        if fvg['status'] == 'active':
            fvg_color = 'rgba(0, 255, 0, 0.2)' if fvg['type'] == 'bullish' else 'rgba(255, 0, 0, 0.2)'
            
            # Create rectangle for FVG
            fig.add_shape(
                type="rect",
                x0=candles.index[fvg['start_idx']],
                x1=candles.index[min(fvg['end_idx'] + 10, len(candles)-1)],
                y0=fvg['bottom'],
                y1=fvg['top'],
                fillcolor=fvg_color,
                opacity=0.5,
                line=dict(width=0),
                layer="below"
            )
    
    # Update layout
    fig.update_layout(
        title=f'{symbol} - {timeframe} Timeframe',
        xaxis_title='Date',
        yaxis_title='Price',
        xaxis_rangeslider_visible=False,
        template='plotly_white',
        height=600,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        margin=dict(l=50, r=50, t=80, b=50)
    )
    
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    
    return fig

# Main dashboard
st.title("Crypto Trading Signals Dashboard")

# Tabs for different sections
tab1, tab2, tab3, tab4 = st.tabs(["📊 Active Signals", "📈 Market Analysis", "📋 Historical Signals", "⚙️ System Status"])

# Tab 1: Active Signals
with tab1:
    # Button to manually generate signals
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.subheader("Active Trading Signals")
    
    with col2:
        if st.button("Generate New Signals", key="gen_signals"):
            new_signals = generate_new_signals()
            # Save to file
            with open("signals.json", "w") as f:
                json.dump({
                    "generated_at": datetime.now().isoformat(),
                    "signals": new_signals
                }, f, indent=2, default=str)
            st.success("Signals generated successfully!")
            # Force reload
            st.rerun()
    
    with col3:
        last_update = load_signals().get("generated_at")
        if last_update:
            st.info(f"Last updated: {format_datetime(last_update)}")
        else:
            st.info("No signals generated yet")
    
    # Load signals
    signal_data = load_signals()
    signals = signal_data.get("signals", {})
    
    if not signals:
        st.info("No active signals available. Click 'Generate New Signals' to scan the market.")
    else:
        # Create a container for each symbol
        for symbol, symbol_signals in signals.items():
            if not symbol_signals:
                continue
                
            st.markdown(f"### {symbol}")
            
            for i, signal in enumerate(symbol_signals):
                # Determine signal class and confidence class
                signal_class = signal['type']
                confidence = signal['confidence']
                confidence_class = "high" if confidence >= 80 else "medium" if confidence >= 60 else "low"
                
                # Create signal card using native Streamlit components
                signal_color = "green" if signal['type'] == 'long' else "red"
                
                # Create a container with border styling
                with st.container():
                    # Apply custom styling with CSS hack (limited but works)
                    st.markdown(f"""
                    <div style="border-left: 5px solid {signal_color}; padding-left: 10px;">
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Header with signal type and confidence
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.subheader(f"{signal['type'].upper()} {signal['symbol']} - {signal['timeframe_combo']}")
                    with col2:
                        confidence_color = "green" if confidence >= 80 else "orange" if confidence >= 60 else "red"
                        st.markdown(f"<h4 style='color: {confidence_color}; text-align: right;'>{signal['confidence']}% Confidence</h4>", unsafe_allow_html=True)
                    
                    # Price information in columns
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Entry Price", f"${signal['entry']:.4f}")
                    with col2:
                        st.metric("Current Price", f"${signal['current_price']:.4f}")
                    with col3:
                        st.metric("Stop Loss", f"${signal['stop']:.4f}")
                    with col4:
                        st.metric("Target", f"${signal['target']:.4f}")
                    
                    # Position information in columns
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Position Size", f"{signal['position_size']['units']:.6f} units (${signal['position_size']['position_value']:.2f})")
                    with col2:
                        st.metric("Risk", f"${signal['position_size']['max_loss']:.2f} ({signal['position_size']['risk_percentage']:.2f}%)")
                    
                    # Reasons as a bulleted list
                    st.write("**Reasons:**")
                    for reason in signal['reasons']:
                        st.write(f"• {reason}")
                    
                    st.markdown("---")
                
                # Show chart for this signal
                chart_expander = st.expander("Show Chart", expanded=False)
                with chart_expander:
                    timeframe = signal['timeframe_combo'].split('->')[0]  # Get the higher timeframe
                    fig = plot_candlestick_chart(signal['symbol'], timeframe, [signal])
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)

# Tab 2: Market Analysis
with tab2:
    st.subheader("Market Analysis")
    
    # Select trading pair and timeframe
    col1, col2 = st.columns(2)
    with col1:
        analysis_pair = st.selectbox("Select Trading Pair", selected_pairs, key="analysis_pair")
    with col2:
        analysis_tf = st.selectbox("Select Timeframe", ["1d", "4h", "1h", "15m", "5m"], key="analysis_tf")
    
    # Get data and show chart
    with st.spinner("Loading market data..."):
        candles = client.get_candles(analysis_pair, analysis_tf, limit=100)
        
        if candles is not None and len(candles) > 0:
            # Create metrics row
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                latest_close = candles['close'].iloc[-1]
                prev_close = candles['close'].iloc[-2]
                pct_change = ((latest_close - prev_close) / prev_close) * 100
                color = "green" if pct_change >= 0 else "red"
                
                st.metric(
                    "Current Price", 
                    f"${latest_close:.2f}", 
                    f"{pct_change:.2f}%",
                    delta_color="normal" if pct_change >= 0 else "inverse"
                )
            
            with col2:
                vol_24h = candles['volume'].iloc[-1]
                prev_vol = candles['volume'].iloc[-2]
                vol_change = ((vol_24h - prev_vol) / prev_vol) * 100
                
                st.metric(
                    "Volume", 
                    f"${vol_24h:.2f}", 
                    f"{vol_change:.2f}%",
                    delta_color="normal" if vol_change >= 0 else "inverse"
                )
            
            with col3:
                high_24h = candles['high'].iloc[-1]
                low_24h = candles['low'].iloc[-1]
                range_pct = ((high_24h - low_24h) / low_24h) * 100
                
                st.metric("Range", f"${high_24h:.2f} - ${low_24h:.2f}", f"{range_pct:.2f}%")
            
            with col4:
                # Daily bias
                daily_candles = client.get_candles(analysis_pair, "1d", limit=10)
                if daily_candles is not None and len(daily_candles) > 1:
                    from analyzers import daily_bias
                    bias_result = daily_bias.analyze_daily_bias(daily_candles)
                    
                    st.metric(
                        "Daily Bias", 
                        bias_result['bias'].capitalize(),
                        bias_result['reason'] if 'reason' in bias_result else None
                    )
            
            # Technical Analysis section
            st.subheader("Technical Analysis")
            
            # Create tabs for different analysis aspects
            tab_chart, tab_fvg, tab_liq, tab_ob = st.tabs(["Chart", "Fair Value Gaps", "Liquidity", "Order Blocks"])
            
            with tab_chart:
                fig = plot_candlestick_chart(analysis_pair, analysis_tf)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
            
            with tab_fvg:
                # Detect fair value gaps
                fvgs = fair_value_gaps.detect_fair_value_gaps(candles)
                
                if fvgs:
                    st.write(f"Found {len(fvgs)} fair value gaps")
                    
                    # Create a dataframe to display FVGs
                    fvg_data = []
                    for fvg in fvgs:
                        fvg_data.append({
                            "Type": fvg['type'].capitalize(),
                            "Status": fvg['status'].capitalize(),
                            "Top": f"${fvg['top']:.2f}",
                            "Bottom": f"${fvg['bottom']:.2f}",
                            "Size": f"${fvg['size']:.2f}",
                            "Date": candles.index[fvg['start_idx']].strftime("%Y-%m-%d %H:%M")
                        })
                    
                    fvg_df = pd.DataFrame(fvg_data)
                    st.dataframe(fvg_df, use_container_width=True)
                    
                    # Plot FVGs on chart
                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots
                    
                    fig = make_subplots(rows=1, cols=1)
                    
                    # Add candlestick chart
                    fig.add_trace(go.Candlestick(
                        x=candles.index,
                        open=candles['open'],
                        high=candles['high'],
                        low=candles['low'],
                        close=candles['close'],
                        name='Price'
                    ))
                    
                    # Add FVGs as colored rectangles
                    for fvg in fvgs:
                        fvg_color = 'rgba(0, 255, 0, 0.2)' if fvg['type'] == 'bullish' else 'rgba(255, 0, 0, 0.2)'
                        
                        # Create rectangle for FVG
                        fig.add_shape(
                            type="rect",
                            x0=candles.index[fvg['start_idx']],
                            x1=candles.index[min(fvg['end_idx'] + 10, len(candles)-1)],
                            y0=fvg['bottom'],
                            y1=fvg['top'],
                            fillcolor=fvg_color,
                            opacity=0.5,
                            line=dict(width=0),
                            layer="below"
                        )
                    
                    # Update layout
                    fig.update_layout(
                        title=f'Fair Value Gaps - {analysis_pair} {analysis_tf}',
                        xaxis_rangeslider_visible=False,
                        height=600
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No fair value gaps detected in the current timeframe")
            
            with tab_liq:
                # Analyze liquidity
                liq_data = liquidity.analyze_range_liquidity(candles)
                
                if liq_data:
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("Internal Range Liquidity")
                        
                        # Internal highs
                        st.write("Internal Highs:")
                        if liq_data['internal']['highs']:
                            int_high_data = []
                            for level in liq_data['internal']['highs']:
                                int_high_data.append({
                                    "Level": f"${level['level']:.2f}",
                                    "Premium/Discount": level['premium_discount'].capitalize(),
                                    "Date": level['timestamp'].strftime("%Y-%m-%d %H:%M")
                                })
                            
                            st.dataframe(pd.DataFrame(int_high_data), use_container_width=True)
                        else:
                            st.info("No internal highs detected")
                        
                        # Internal lows
                        st.write("Internal Lows:")
                        if liq_data['internal']['lows']:
                            int_low_data = []
                            for level in liq_data['internal']['lows']:
                                int_low_data.append({
                                    "Level": f"${level['level']:.2f}",
                                    "Premium/Discount": level['premium_discount'].capitalize(),
                                    "Date": level['timestamp'].strftime("%Y-%m-%d %H:%M")
                                })
                            
                            st.dataframe(pd.DataFrame(int_low_data), use_container_width=True)
                        else:
                            st.info("No internal lows detected")
                    
                    with col2:
                        st.subheader("External Range Liquidity")
                        
                        # External highs
                        st.write("External Highs:")
                        if liq_data['external']['highs']:
                            ext_high_data = []
                            for level in liq_data['external']['highs']:
                                ext_high_data.append({
                                    "Level": f"${level['level']:.2f}",
                                    "Date": level['timestamp'].strftime("%Y-%m-%d %H:%M")
                                })
                            
                            st.dataframe(pd.DataFrame(ext_high_data), use_container_width=True)
                        else:
                            st.info("No external highs detected")
                        
                        # External lows
                        st.write("External Lows:")
                        if liq_data['external']['lows']:
                            ext_low_data = []
                            for level in liq_data['external']['lows']:
                                ext_low_data.append({
                                    "Level": f"${level['level']:.2f}",
                                    "Date": level['timestamp'].strftime("%Y-%m-%d %H:%M")
                                })
                            
                            st.dataframe(pd.DataFrame(ext_low_data), use_container_width=True)
                        else:
                            st.info("No external lows detected")
                    
                    # Plot liquidity levels on chart
                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots
                    
                    fig = make_subplots(rows=1, cols=1)
                    
                    # Add candlestick chart
                    fig.add_trace(go.Candlestick(
                        x=candles.index,
                        open=candles['open'],
                        high=candles['high'],
                        low=candles['low'],
                        close=candles['close'],
                        name='Price'
                    ))
                    
                    # Add internal liquidity levels
                    for level in liq_data['internal']['highs']:
                        fig.add_shape(
                            type="line",
                            x0=candles.index[0],
                            x1=candles.index[-1],
                            y0=level['level'],
                            y1=level['level'],
                            line=dict(color="darkred", width=1, dash="dash"),
                        )
                    
                    for level in liq_data['internal']['lows']:
                        fig.add_shape(
                            type="line",
                            x0=candles.index[0],
                            x1=candles.index[-1],
                            y0=level['level'],
                            y1=level['level'],
                            line=dict(color="darkgreen", width=1, dash="dash"),
                        )
                    
                    # Add external liquidity levels
                    for level in liq_data['external']['highs']:
                        fig.add_shape(
                            type="line",
                            x0=candles.index[0],
                            x1=candles.index[-1],
                            y0=level['level'],
                            y1=level['level'],
                            line=dict(color="red", width=2),
                        )
                    
                    for level in liq_data['external']['lows']:
                        fig.add_shape(
                            type="line",
                            x0=candles.index[0],
                            x1=candles.index[-1],
                            y0=level['level'],
                            y1=level['level'],
                            line=dict(color="green", width=2),
                        )
                    
                    # Update layout
                    fig.update_layout(
                        title=f'Liquidity Levels - {analysis_pair} {analysis_tf}',
                        xaxis_rangeslider_visible=False,
                        height=600
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No liquidity levels detected in the current timeframe")
            
            with tab_ob:
                # Detect order blocks
                obs = order_blocks.detect_order_blocks(candles)
                
                if obs:
                    st.write(f"Found {len(obs)} order blocks")
                    
                    # Create a dataframe to display order blocks
                    ob_data = []
                    for ob in obs:
                        ob_data.append({
                            "Type": ob['type'].capitalize(),
                            "Status": ob['status'].capitalize(),
                            "Top": f"${ob['top']:.2f}",
                            "Bottom": f"${ob['bottom']:.2f}",
                            "Date": ob['timestamp'].strftime("%Y-%m-%d %H:%M")
                        })
                    
                    ob_df = pd.DataFrame(ob_data)
                    st.dataframe(ob_df, use_container_width=True)
                    
                    # Plot order blocks on chart
                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots
                    
                    fig = make_subplots(rows=1, cols=1)
                    
                    # Add candlestick chart
                    fig.add_trace(go.Candlestick(
                        x=candles.index,
                        open=candles['open'],
                        high=candles['high'],
                        low=candles['low'],
                        close=candles['close'],
                        name='Price'
                    ))
                    
                    # Add order blocks as colored rectangles
                    for ob in obs:
                        if ob['status'] == 'active':
                            ob_color = 'rgba(0, 0, 255, 0.2)' if ob['type'] == 'bullish' else 'rgba(255, 0, 255, 0.2)'
                            
                            # Create rectangle for order block
                            fig.add_shape(
                                type="rect",
                                x0=ob['timestamp'],
                                x1=candles.index[-1],
                                y0=ob['bottom'],
                                y1=ob['top'],
                                fillcolor=ob_color,
                                opacity=0.5,
                                line=dict(width=0),
                                layer="below"
                            )
                    
                    # Update layout
                    fig.update_layout(
                        title=f'Order Blocks - {analysis_pair} {analysis_tf}',
                        xaxis_rangeslider_visible=False,
                        height=600
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No order blocks detected in the current timeframe")
        else:
            st.warning(f"No data available for {analysis_pair} on {analysis_tf} timeframe")

# Tab 3: Historical Signals
with tab3:
    st.subheader("Historical Signals")
    
    # Placeholder for historical signals
    st.info("Historical signal tracking will be implemented in future updates.")
    
    # Create a placeholder for storing historical signals
    if "historical_signals" not in st.session_state:
        st.session_state.historical_signals = []
    
    # Display placeholder data
    example_data = [
        {"symbol": "BTCUSDT", "type": "long", "entry": 63245.50, "exit": 65120.75, "result": "Win", "profit": 1875.25, "date": "2025-02-25"},
        {"symbol": "ETHUSDT", "type": "short", "entry": 3350.25, "exit": 3275.50, "result": "Win", "profit": 74.75, "date": "2025-02-27"},
        {"symbol": "BTCUSDT", "type": "short", "entry": 67150.75, "exit": 67780.50, "result": "Loss", "profit": -629.75, "date": "2025-02-28"}
    ]
    
    # Create a dataframe
    hist_df = pd.DataFrame(example_data)
    
    # Add styling
    def color_result(val):
        color = 'green' if val == 'Win' else 'red'
        return f'background-color: {color}; color: white'
    
    def color_profit(val):
        color = 'green' if val > 0 else 'red'
        return f'color: {color}'
    
    # Apply styling
    styled_df = hist_df.style.applymap(color_result, subset=['result']).applymap(color_profit, subset=['profit'])
    
    # Display dataframe
    st.dataframe(styled_df, use_container_width=True)
    
    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        win_rate = len(hist_df[hist_df['result'] == 'Win']) / len(hist_df) * 100
        st.metric("Win Rate", f"{win_rate:.1f}%")
    
    with col2:
        total_profit = hist_df['profit'].sum()
        st.metric("Total Profit", f"${total_profit:.2f}")
    
    with col3:
        avg_win = hist_df[hist_df['result'] == 'Win']['profit'].mean()
        st.metric("Average Win", f"${avg_win:.2f}")
    
    with col4:
        avg_loss = abs(hist_df[hist_df['result'] == 'Loss']['profit'].mean())
        st.metric("Average Loss", f"${avg_loss:.2f}")

# Tab 4: System Status
with tab4:
    st.subheader("System Status")
    
    # System settings
    st.markdown("### System Settings")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        **Risk Management:**
        - Account Size: ${}
        - Risk Per Trade: ${}
        - Leverage: {}x
        """.format(account_size, risk_per_trade, leverage))
    
    with col2:
        st.markdown("""
        **Trading Pairs:**
        - {}
        """.format(", ".join(selected_pairs)))
    
    with col3:
        st.markdown("""
        **Timeframes:**
        - {}
        """.format(", ".join(selected_timeframes)))
    
    # API Status
    st.markdown("### API Status")
    
    try:
        # Test API connection
        server_time = client.client.get_server_time()
        server_time_dt = datetime.fromtimestamp(server_time['serverTime']/1000)
        
        st.success("Binance API Connection: Online")
        st.info(f"Server Time: {server_time_dt}")
        
        # Get exchange info
        exchange_info = client.client.get_exchange_info()
        
        # Show rate limits
        st.markdown("#### Rate Limits")
        rate_limits = exchange_info['rateLimits']
        
        rate_data = []
        for limit in rate_limits:
            rate_data.append({
                "Type": limit['rateLimitType'],
                "Interval": limit['interval'],
                "Limit": limit['limit']
            })
        
        st.dataframe(pd.DataFrame(rate_data), use_container_width=True)
        
    except Exception as e:
        st.error(f"Binance API Connection: Error - {str(e)}")
    
    # System logs
    st.markdown("### System Logs")
    
    # Create a placeholder for logs
    if "system_logs" not in st.session_state:
        st.session_state.system_logs = [
            {"timestamp": datetime.now(), "level": "INFO", "message": "System initialized"},
            {"timestamp": datetime.now() - timedelta(minutes=5), "level": "INFO", "message": "Signal scan completed"},
            {"timestamp": datetime.now() - timedelta(minutes=10), "level": "WARNING", "message": "API rate limit approaching"}
        ]
    
    # Convert logs to dataframe
    logs_df = pd.DataFrame(st.session_state.system_logs)
    logs_df['timestamp'] = logs_df['timestamp'].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S"))
    
    # Display logs
    st.dataframe(logs_df, use_container_width=True)

# Auto refresh functionality
if auto_refresh:
    time.sleep(1)  # Small delay to prevent UI jumps
    st.markdown(f"<div style='text-align: center; color: gray;'>Auto-refreshing in {refresh_interval} minutes</div>", unsafe_allow_html=True)
    time.sleep(refresh_interval * 60)
    st.rerun()