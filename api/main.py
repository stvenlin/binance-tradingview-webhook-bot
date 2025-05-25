import os
import json
from trade import future_trade
from decimal import Decimal
from util import floor_to
from api.constant import OrderSide, OrderType

import config
from flask import Flask, request
from api.binance_spot import BinanceSpotHttpClient
from api.binance_future import BinanceFutureHttpClient, OrderSide, OrderType
from event import EventEngine, Event, EVENT_TIMER, EVENT_SIGNAL

app = Flask(__name__)

@app.route('/', methods=['GET'])
def welcome():
    return "Hello Flask, This is for testing. If you receive this message, it means your configuration is correct."


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = json.loads(request.data)
        print(data)
        if data.get('passphrase', None) != config.WEBHOOK_PASSPHRASE:
            return "failure: passphrase is incorrect."

        future_trade(data)

        return "success"
    except Exception as error:
        print(f"error: {error}")
        return "failure"

def future_trade(data: dict):
    symbol = data.get("symbol")
    action = data.get("action", "").upper()
    entry_price = float(data.get("price", 0))
    tp = float(data.get("tp", 0))
    sl = float(data.get("sl", 0))

    # 获取账户余额
    account_info = binance_future_client.get_account_info()[1]
    usdt_balance = Decimal("0")
    for asset in account_info.get("assets", []):
        if asset["asset"] == "USDT":
            usdt_balance = Decimal(asset["walletBalance"])
            break

    # 获取交易精度
    exchange_info = binance_future_client.exchangeInfo()[1]
    symbol_info = next(s for s in exchange_info["symbols"] if s["symbol"] == symbol)
    qty_step_size = Decimal("1.0")
    price_tick_size = Decimal("0.1")
    for f in symbol_info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            qty_step_size = Decimal(f["stepSize"])
        if f["filterType"] == "PRICE_FILTER":
            price_tick_size = Decimal(f["tickSize"])

    # 计算下单数量（50% USDT 余额）
    amount_to_use = usdt_balance * Decimal("0.5")
    quantity = amount_to_use / Decimal(entry_price)
    quantity = floor_to(quantity, qty_step_size)

    side = OrderSide.BUY if action == "LONG" else OrderSide.SELL
    opposite_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

    # 市价开单
    order_id = binance_future_client.get_client_order_id()
    binance_future_client.place_order(
        symbol=symbol,
        order_side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        price=Decimal("0"),
        client_order_id=order_id
    )

    # 止盈单（限价）
    binance_future_client.place_order(
        symbol=symbol,
        order_side=opposite_side,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        price=floor_to(tp, price_tick_size),
        time_inforce="GTC"
    )

    # 止损单（触发）
    binance_future_client.place_order(
        symbol=symbol,
        order_side=opposite_side,
        order_type=OrderType.STOP,
        quantity=quantity,
        price=floor_to(sl, price_tick_size),
        stop_price=floor_to(sl, price_tick_size),
        time_inforce="GTC"
    )

    print(f"{action} {symbol} 成交，数量：{quantity}，TP：{tp}，SL：{sl}")

def timer_event(event: Event):
    global cancel_orders_timer
    global query_orders_timer

    cancel_orders_timer += 1
    query_orders_timer += 1

    if cancel_orders_timer > config.CANCEL_ORDERS_IN_SECONDS:
        cancel_orders_timer = 0
        for strategy_name in future_strategy_order_dict.keys():
            order_id = future_strategy_order_dict[strategy_name]
            if not order_id:
                continue
            symbol = config.strategies.get(strategy_name, {}).get('symbol', "")
            binance_future_client.cancel_order(symbol, client_order_id=order_id)

    if query_orders_timer > config.QUERY_ORDERS_STATUS_IN_SECONDS:
        query_orders_timer = 0
        for strategy_name in future_strategy_order_dict.keys():
            order_id = future_strategy_order_dict[strategy_name]
            if not order_id:
                continue
            symbol = config.strategies.get(strategy_name, {}).get('symbol', "")
            status_code, order = binance_future_client.get_order(symbol, client_order_id=order_id)
            if status_code == 200 and order:
                if order.get('status') in ['CANCELED', 'FILLED']:
                    side = order.get('side')
                    strategy_config = config.strategies.get(strategy_name, {})
                    executed_qty = Decimal(order.get('executedQty', "0"))
                    if side == "BUY":
                        strategy_config['pos'] = strategy_config['pos'] + executed_qty
                    elif side == "SELL":
                        strategy_config['pos'] = strategy_config['pos'] - executed_qty
                    config.strategies[strategy_name] = strategy_config
                    future_strategy_order_dict[strategy_name] = None
            elif status_code == 400 and order.get('code') == -2013:
                future_strategy_order_dict[strategy_name] = None

    for strategy_name in future_signal_dict.keys():
        orderid = future_strategy_order_dict.get(strategy_name, None)
        if not orderid:
            data = future_signal_dict.get(strategy_name, None)
            if data:
                future_trade(data)

    for key in spot_signal_dict.keys():
        # TODO: Add your spot trading logic here if needed
        pass


def signal_event(event: Event):
    data = event.data
    strategy_name = data.get('strategy_name', None)
    if not strategy_name:
        print("config from tradingview does not have strategy_name key.")
        return

    if data.get('exchange', None) == 'binance_future':
        future_signal_dict[strategy_name] = data
        future_trade(data)

    elif data.get('exchange', None) == 'binance_spot':
        future_signal_dict[strategy_name] = data
        # Add spot logic here


if __name__ == '__main__':
    future_signal_dict = {}
    spot_signal_dict = {}
    future_strategy_order_dict = {}

    cancel_orders_timer = 0
    query_orders_timer = 0

    binance_spot_client = BinanceSpotHttpClient(api_key=config.API_KEY, secret=config.API_SECRET)
    binance_future_client = BinanceFutureHttpClient(api_key=config.API_KEY, secret=config.API_SECRET)

    event_engine = EventEngine(interval=1)
    event_engine.start()
    event_engine.register(EVENT_TIMER, timer_event)
    event_engine.register(EVENT_SIGNAL, signal_event)

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
