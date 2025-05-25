from decimal import Decimal
from binance_future import BinanceFutureHttpClient
from constant import OrderSide, OrderType
from util import floor_to

client = BinanceFutureHttpClient(api_key="你的API", secret="你的SECRET")

def future_trade(data):
    symbol = data["symbol"]
    action = data["action"]
    entry_price = float(data["price"])
    tp = float(data["tp"])
    sl = float(data["sl"])

    # 获取余额
    account_info = client.get_account_info()[1]
    usdt_balance = Decimal("0")
    for asset in account_info.get("assets", []):
        if asset["asset"] == "USDT":
            usdt_balance = Decimal(asset["walletBalance"])
            break

    # 获取精度
    exchange_info = client.exchangeInfo()[1]
    symbol_info = next(s for s in exchange_info["symbols"] if s["symbol"] == symbol)
    qty_step_size = Decimal("1.0")
    price_tick_size = Decimal("0.1")
    for f in symbol_info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            qty_step_size = Decimal(f["stepSize"])
        if f["filterType"] == "PRICE_FILTER":
            price_tick_size = Decimal(f["tickSize"])

    # 计算下单数量（50%余额）
    amount_to_use = usdt_balance * Decimal("0.5")
    quantity = amount_to_use / Decimal(entry_price)
    quantity = floor_to(quantity, qty_step_size)

    side = OrderSide.BUY if action == "LONG" else OrderSide.SELL

    # 市价单
    client.place_order(
        symbol=symbol,
        order_side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        price=Decimal("0"),
    )

    # 止盈单
    client.place_order(
        symbol=symbol,
        order_side=OrderSide.SELL if action == "LONG" else OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        price=floor_to(tp, price_tick_size),
        time_inforce="GTC"
    )

    # 止损单
    client.place_order(
        symbol=symbol,
        order_side=OrderSide.SELL if action == "LONG" else OrderSide.BUY,
        order_type=OrderType.STOP,
        quantity=quantity,
        price=floor_to(sl, price_tick_size),
        stop_price=floor_to(sl, price_tick_size)
    )

    return {"status": "success", "symbol": symbol, "side": action, "qty": str(quantity)}
