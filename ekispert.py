"""
駅すぱあとAPIとの通信を担当するモジュール。

STEP1: search_course()      … 出発駅/到着駅/経由駅から経路を検索し、
                               払い戻し計算に必要な「シリアライズデータ」を取得する
STEP2: search_repayment()   … シリアライズデータと定期券情報から、払い戻し金額を計算する

前担当からの引き継ぎ時点で、公式ドキュメント
(https://docs.ekispert.com/v1/api/course/repayment.html ほか) に基づいて
一度完成していたコードをそのまま採用しています。
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("EKISPERT_API_KEY")
BASE_URL = "https://api.ekispert.jp/v1/json"


def _extract_api_error(response) -> str:
    """
    駅すぱあとAPIが返す非2xxレスポンスから、人間が読めるエラーメッセージ本文を取り出す。
    JSONで来る場合・XML/プレーンテキストで来る場合の両方に対応する。
    """
    try:
        data = response.json()
        # {"ResultSet": {"Error": {"code": "...", "text": "..."}}} のような形式を想定
        result_set = data.get("ResultSet", data)
        error_info = result_set.get("Error") if isinstance(result_set, dict) else None
        if isinstance(error_info, dict):
            code = error_info.get("code", "")
            text = (
                error_info.get("Message", "")
                or error_info.get("message", "")
                or error_info.get("text", "")
                or error_info.get("Text", "")
            )
            if code or text:
                return f"{text}（コード: {code}）" if code else text
        return str(data)[:500]
    except ValueError:
        # JSONで返ってこない場合は本文をそのまま（長すぎる場合は切り詰めて）返す
        return (response.text or "")[:500]



def search_course(from_station, to_station, via_stations=None, answer_count: int = 5) -> dict:
    """
    STEP1: 経路検索APIで経路の候補を取得し、それぞれのシリアライズデータと経路情報を返す
    GET /v1/json/search/course/extreme

    from_station / to_station / via_stations には
    - 駅名テキスト（例：「新宿」）
    - 駅コード（例：「22741」）
    のどちらでも渡せる。
    """
    url = f"{BASE_URL}/search/course/extreme"

    via_stations = [str(v).strip() for v in (via_stations or []) if v and str(v).strip()]
    via_list = ":".join([str(from_station), *via_stations, str(to_station)])

    params = {
        "key": API_KEY,
        "viaList": via_list,
        "searchType": "plain",
        "answerCount": answer_count,
        "sort": "teiki6",
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        if not response.ok:
            return {
                "success": False,
                "message": f"{response.status_code} エラー：{_extract_api_error(response)}",
            }
        data = response.json()

        result_set = data.get("ResultSet", {})
        course_list = result_set.get("Course", None)

        if course_list is None:
            return {"success": False, "message": "経路が見つかりませんでした。駅名を確認してください。"}

        if isinstance(course_list, dict):
            course_list = [course_list]

        candidates = []
        for course in course_list:
            teiki_info = course.get("Teiki", None)
            if teiki_info is None:
                continue

            serialize_data = course.get("SerializeData", "")
            display_route = teiki_info.get("DisplayRoute", "")
            if not serialize_data:
                continue

            transport_type = "電車"
            route = course.get("Route", {})
            line_list = route.get("Line", [])
            if isinstance(line_list, dict):
                line_list = [line_list]

            for line in line_list:
                line_type = ""
                type_info = line.get("Type", "")
                if isinstance(type_info, dict):
                    line_type = type_info.get("text", "") or type_info.get("#text", "")
                elif isinstance(type_info, str):
                    line_type = type_info
                line_name = line.get("Name", "")
                if "バス" in line_name or "bus" in line_type.lower():
                    transport_type = "バス"
                    break

            price_list = course.get("Price", [])
            if isinstance(price_list, dict):
                price_list = [price_list]
            teiki_prices = {}
            for p in price_list:
                kind = p.get("kind", "")
                if kind in ("Teiki1Summary", "Teiki3Summary", "Teiki6Summary", "Teiki12Summary"):
                    months = int(kind.replace("Teiki", "").replace("Summary", ""))
                    oneway = p.get("Oneway")
                    if oneway is not None:
                        try:
                            teiki_prices[months] = int(oneway)
                        except (TypeError, ValueError):
                            pass

            candidates.append({
                "serialize_data": serialize_data,
                "display_route": display_route,
                "transport_type": transport_type,
                "teiki_prices": teiki_prices,
            })

        if not candidates:
            return {"success": False, "message": "定期券経路が見つかりませんでした。定期券が発売されていない経路の可能性があります。"}

        return {"success": True, "candidates": candidates}

    except requests.exceptions.Timeout:
        return {"success": False, "message": "APIへの接続がタイムアウトしました。"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "APIへの接続に失敗しました。インターネット接続を確認してください。"}
    except Exception as e:
        return {"success": False, "message": f"エラーが発生しました：{str(e)}"}



def search_repayment(
    serialize_data: str,
    start_date: str,
    repayment_date: str,
    validity_period: int
) -> dict:
    """
    STEP2: 払い戻し計算APIで払い戻し金額を取得する
    GET /v1/json/course/repayment

    :param serialize_data: 経路シリアライズデータ（search_courseで取得したもの）
    :param start_date: 定期券の有効開始日（YYYYMMDD形式）
    :param repayment_date: 払い戻し日（YYYYMMDD形式）
    :param validity_period: 定期券の有効期間（1, 3, 6）
    :return: 払い戻し金額・手数料・使用済み金額を含む辞書
    """
    url = f"{BASE_URL}/course/repayment"

    params = {
        "key": API_KEY,
        "serializeData": serialize_data,
        "startDate": start_date,
        "repaymentDate": repayment_date,
        "validityPeriod": validity_period,
        "checkEngineVersion": "false",  # 検索時と計算時でエンジンバージョンが異なってもエラーにしない
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        if not response.ok:
            return {
                "success": False,
                "message": f"{response.status_code} エラー：{_extract_api_error(response)}",
            }
        data = response.json()

        result_set = data.get("ResultSet", {})
        repayment_list = result_set.get("RepaymentList", None)

        if repayment_list is None:
            return {"success": False, "message": "払い戻し情報が取得できませんでした。"}

        ticket = repayment_list.get("RepaymentTicket", None)
        if ticket is None:
            return {"success": False, "message": "払い戻しチケット情報が取得できませんでした。"}

        # 複数チケットの場合は合算する
        if isinstance(ticket, list):
            total_repay = 0
            total_fee = 0
            total_used = 0
            total_pay = 0
            for t in ticket:
                if t.get("calculateTarget", "False") == "True":
                    total_repay += int(t.get("repayPriceValue", 0))
                    total_fee += int(t.get("feePriceValue", 0))
                    total_used += int(t.get("usedPriceValue", 0))
                    total_pay += int(t.get("payPriceValue", 0))
        else:
            total_repay = int(ticket.get("repayPriceValue", 0))
            total_fee = int(ticket.get("feePriceValue", 0))
            total_used = int(ticket.get("usedPriceValue", 0))
            total_pay = int(ticket.get("payPriceValue", 0))

        refund_after_fee = total_repay - total_fee
        if refund_after_fee < 0:
            refund_after_fee = 0

        return {
            "success": True,
            "repay_price": total_repay,             # 払い戻し金額（手数料前）
            "fee_price": total_fee,                 # 手数料
            "used_price": total_used,               # 使用済み金額
            "pay_price": total_pay,                 # 購入金額
            "refund_after_fee": refund_after_fee,    # 最終払い戻し額（手数料控除後）
        }

    except requests.exceptions.Timeout:
        return {"success": False, "message": "APIへの接続がタイムアウトしました。"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "APIへの接続に失敗しました。インターネット接続を確認してください。"}
    except Exception as e:
        return {"success": False, "message": f"エラーが発生しました：{str(e)}"}

def search_station(name: str) -> dict:
    """
    駅名から候補駅一覧を取得する
    GET /v1/json/station/light?name=...
    同名駅が複数ある場合（例：北野）に、ユーザーが選択できるよう候補を返す

    :param name: 駅名（部分一致でも可）
    :return: {"success": True, "stations": [{"code": "...", "label": "..."}, ...]}
    """
    url = f"{BASE_URL}/station/light"

    params = {
        "key": API_KEY,
        "name": name,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        if not response.ok:
            return {
                "success": False,
                "message": f"{response.status_code} エラー：{_extract_api_error(response)}",
            }
        data = response.json()

        result_set = data.get("ResultSet", {})
        point_list = result_set.get("Point", None)

        if point_list is None:
            return {"success": False, "message": f"「{name}」に一致する駅が見つかりませんでした。"}

        if isinstance(point_list, dict):
            point_list = [point_list]

        stations = []
        for point in point_list:
            station = point.get("Station", {})
            code = station.get("code", "")
            station_name = station.get("Name", "")

            # 都道府県名
            pref = point.get("Prefecture", {})
            pref_name = pref.get("Name", "") if isinstance(pref, dict) else ""

            # 路線名（複数ある場合は最初の1件）
            lines = point.get("GeoPoint", {})
            rail_list = point.get("Rail", [])
            if isinstance(rail_list, dict):
                rail_list = [rail_list]
            rail_names = [r.get("Name", "") for r in rail_list if r.get("Name")]
            rail_label = "・".join(rail_names[:2]) if rail_names else ""

            # ラベル例：「北野（東京都）京王線」
            label_parts = [station_name]
            if pref_name:
                label_parts.append(f"（{pref_name}）")
            if rail_label:
                label_parts.append(f" {rail_label}")
            label = "".join(label_parts)

            stations.append({
                "code": code,
                "name": station_name,
                "label": label,
            })

        return {"success": True, "stations": stations}

    except requests.exceptions.Timeout:
        return {"success": False, "message": "APIへの接続がタイムアウトしました。"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "APIへの接続に失敗しました。インターネット接続を確認してください。"}
    except Exception as e:
        return {"success": False, "message": f"エラーが発生しました：{str(e)}"}

