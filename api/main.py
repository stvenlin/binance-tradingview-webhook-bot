import os
import json
from api.future_trade_handler import future_trade
from decimal import Decimal

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

        event = Event(EVENT_SIGNAL, data=data)
        event_engine.put(event)

        return "success"
    except Exception as error:
        print(f"error: {error}")
        return "failure"

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
