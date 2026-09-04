"""
1件分の払い戻し計算をまとめて行うための薄いラッパーモジュール。

手入力モード・CSV取込モードの両方から呼び出せるよう、
「出発駅・到着駅・経由駅・定期券月数・開始日・払戻日」を受け取り、
ekispert.py の search_course() → search_repayment() を順番に呼び出して
1件分の結果（電車/バス、経路、金額、手数料など）をまとめて返す。
"""

from datetime import date

from ekispert import search_course, search_repayment


def calc_repayment_for_one(
    from_station: str,
    to_station: str,
    via_station: str,
    teiki_months: int,
    start_date,
    cancel_date,
) -> dict:
    """
    1件分の経路検索＋払い戻し計算をまとめて実行する。

    :param from_station: 出発駅
    :param to_station: 到着駅（降車駅）
    :param via_station: 経由駅（空文字可）
    :param teiki_months: 定期券の月数（1 / 3 / 6）
    :param start_date: 定期券有効開始日（date型 or "YYYYMMDD"文字列）
    :param cancel_date: 定期券解約日／払戻日（date型 or "YYYYMMDD"文字列）
    :return: 以下のキーを持つ辞書
        success            … True/False
        message            … エラー時のメッセージ
        transport_type     … "電車" / "バス"（W列用）
        display_route      … 払い戻し経路の文字列（X列用）
        repay_price        … 払い戻し金額（手数料前）
        fee_price          … 手数料（Z列用）
        refund_after_fee   … 手数料を引いた払戻額（Y列・AA列用）
        pay_price          … 購入金額（参考値）
        used_price         … 使用済み金額（参考値）
    """
    if not from_station or not to_station:
        return {"success": False, "message": "出発駅・到着駅は必須です。"}

    via_stations = [v.strip() for v in str(via_station or "").split(",") if v.strip()]

    course_result = search_course(
        from_station=from_station,
        to_station=to_station,
        via_stations=via_stations,
        answer_count=1,  # CSV一括モードは候補の中から自動で最有力の1件を採用する
    )
    if not course_result["success"]:
        return {"success": False, "message": f"経路取得エラー：{course_result['message']}"}

    best_candidate = course_result["candidates"][0]

    start_date_str = _to_yyyymmdd(start_date)
    cancel_date_str = _to_yyyymmdd(cancel_date)

    repayment_result = search_repayment(
        serialize_data=best_candidate["serialize_data"],
        start_date=start_date_str,
        repayment_date=cancel_date_str,
        validity_period=teiki_months,
    )
    if not repayment_result["success"]:
        return {"success": False, "message": f"計算エラー：{repayment_result['message']}"}

    return {
        "success": True,
        "message": "",
        "transport_type": best_candidate["transport_type"],
        "display_route": best_candidate["display_route"],
        "repay_price": repayment_result["repay_price"],
        "fee_price": repayment_result["fee_price"],
        "refund_after_fee": repayment_result["refund_after_fee"],
        "pay_price": repayment_result["pay_price"],
        "used_price": repayment_result["used_price"],
    }


def _to_yyyymmdd(value) -> str:
    """date型 or 文字列を 'YYYYMMDD' 形式の文字列に変換する"""
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    s = str(value).strip()
    # "2026-04-01" や "2026/04/01" のような区切り文字入りにも対応
    s = s.replace("-", "").replace("/", "")
    return s


def search_route_candidates(from_station: str, to_station: str, via_stations, answer_count: int = 5) -> dict:
    """
    手入力モードの「経路を選択」フロー用：候補経路を複数取得する。
    :return: {"success": True, "candidates": [...]} または {"success": False, "message": ...}
    """
    if not from_station or not to_station:
        return {"success": False, "message": "出発駅・到着駅は必須です。"}
    return search_course(
        from_station=from_station,
        to_station=to_station,
        via_stations=via_stations,
        answer_count=answer_count,
    )


def calc_repayment_from_candidate(
    candidate: dict,
    teiki_months: int,
    start_date,
    cancel_date,
    purchase_price=None,
) -> dict:
    """
    ユーザーが選択した候補経路(candidate)について、払い戻し計算を実行する。
    purchase_priceが指定されている場合、APIが計算した購入金額(pay_price)と比較し、
    金額が食い違っていれば discrepancy として知らせる（APIには渡さず参考表示のみ）。
    """
    start_date_str = _to_yyyymmdd(start_date)
    cancel_date_str = _to_yyyymmdd(cancel_date)

    repayment_result = search_repayment(
        serialize_data=candidate["serialize_data"],
        start_date=start_date_str,
        repayment_date=cancel_date_str,
        validity_period=teiki_months,
    )
    if not repayment_result["success"]:
        return {"success": False, "message": f"計算エラー：{repayment_result['message']}"}

    discrepancy = None
    if purchase_price not in (None, "", 0):
        try:
            purchase_price = int(purchase_price)
            if purchase_price != repayment_result["pay_price"]:
                discrepancy = (
                    f"入力した購入金額（{purchase_price:,}円）と、APIが算出した購入金額"
                    f"（{repayment_result['pay_price']:,}円）が一致しません。運賃改定などの"
                    f"可能性があるため、金額をご確認ください。"
                )
        except (TypeError, ValueError):
            pass

    return {
        "success": True,
        "message": "",
        "transport_type": candidate["transport_type"],
        "display_route": candidate["display_route"],
        "repay_price": repayment_result["repay_price"],
        "fee_price": repayment_result["fee_price"],
        "refund_after_fee": repayment_result["refund_after_fee"],
        "pay_price": repayment_result["pay_price"],
        "used_price": repayment_result["used_price"],
        "discrepancy": discrepancy,
    }
