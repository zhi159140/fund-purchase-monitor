#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基金限购状态监控脚本

监控目标：
- 016057 博时纳斯达克100ETF联接C
- 006075 博时标普500ETF联接C

推送：
- PushPlus txt 文本格式
- 仅发现申购状态变化时推送
"""

import json
import os
import traceback
from datetime import datetime, timezone, timedelta

import requests


API_URL = "https://skills.tiantianfunds.com/ai-smart-skill-service/openapi/skill/invoke"
API_KEY = os.environ.get("TTF_API_KEY")

PUSHPLUS_URL = "https://www.pushplus.plus/send"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")

FUNDS = {
    "016057": "博时纳斯达克100ETF联接C",
    "006075": "博时标普500ETF联接C",
}

BASELINE_STATUS = {
    "016057": "暂停申购",
    "006075": "暂停申购",
}

STATUS_FILE = "fund_purchase_baseline.json"
RESULT_FILE = "fund_purchase_monitor_result.json"
CHINA_TZ = timezone(timedelta(hours=8))


def now_china():
    return datetime.now(CHINA_TZ)


def load_baseline():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        save_baseline(BASELINE_STATUS)
        return BASELINE_STATUS.copy()
    except Exception as e:
        print(f"加载基准状态失败: {e}")
        return BASELINE_STATUS.copy()


def save_baseline(status):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def send_pushplus_text(title, content):
    if not PUSHPLUS_TOKEN:
        print("PushPlus未推送：PUSHPLUS_TOKEN未设置")
        return False

    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "txt",
    }

    try:
        response = requests.post(PUSHPLUS_URL, json=payload, timeout=20)
        result = response.json()
        if result.get("code") == 200:
            print("PushPlus推送成功")
            return True

        print(f"PushPlus推送失败: {result}")
        return False
    except Exception as e:
        print(f"PushPlus推送异常: {e}")
        return False


def get_fund_status(fund_code):
    if not API_KEY:
        print("错误：TTF_API_KEY环境变量未设置")
        return None

    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "skill_id": "FUND_BASE_INFOS",
        "_skill_version": "1.2.0",
        "fcode": fund_code,
    }

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == 0 and "data" in data:
            raw_result = data["data"].get("raw_result", {})
            body = raw_result.get("body", {})
            data_list = body.get("data", [])

            if data_list:
                fund_data = data_list[0]
                return {
                    "code": fund_code,
                    "name": FUNDS.get(fund_code, ""),
                    "sgzt": fund_data.get("SGZT", ""),
                    "max_sg": fund_data.get("MAXSG", ""),
                }

        print(f"API返回数据结构异常: code={data.get('code')}, keys={list(data.keys()) if data else 'None'}")
        return None
    except Exception as e:
        print(f"获取基金 {fund_code} 状态失败: {e}")
        traceback.print_exc()
        return None


def check_status_change(current_status, baseline):
    changes = []

    for code, info in current_status.items():
        if not info:
            continue

        current_sgzt = info["sgzt"]
        baseline_sgzt = baseline.get(code, "")
        if current_sgzt == baseline_sgzt:
            continue

        need_notify = False
        change_type = ""

        if baseline_sgzt == "暂停申购" and current_sgzt in ["开放申购", "限大额"]:
            need_notify = True
            change_type = "恢复申购"
        elif baseline_sgzt in ["开放申购", "限大额"] and current_sgzt == "暂停申购":
            need_notify = True
            change_type = "暂停申购"

        if need_notify:
            changes.append({
                "code": code,
                "name": info["name"],
                "old_status": baseline_sgzt,
                "new_status": current_sgzt,
                "change_type": change_type,
                "max_sg": info["max_sg"],
            })

    return changes


def build_push_text(changes, current_status, timestamp):
    lines = [
        f"基金限购状态变化 - {timestamp}",
        "",
        "变化明细：",
    ]

    for change in changes:
        max_sg = change["max_sg"] if change["max_sg"] not in [None, ""] else "-"
        lines.append(
            "{} {}: {} -> {} ({})，最大申购={}".format(
                change["code"],
                change["name"],
                change["old_status"],
                change["new_status"],
                change["change_type"],
                max_sg,
            )
        )

    lines.append("")
    lines.append("当前状态：")
    for code, info in current_status.items():
        if info:
            max_sg = info["max_sg"] if info["max_sg"] not in [None, ""] else "-"
            lines.append(f"{code} {info['name']}: 申购状态={info['sgzt']}，最大申购={max_sg}")
        else:
            lines.append(f"{code} {FUNDS.get(code, '')}: 获取失败")

    return "\n".join(lines)


def main():
    timestamp = now_china().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== 基金限购状态监控 {timestamp} ===")

    baseline = load_baseline()
    print(f"基准状态: {baseline}")

    current_status = {}
    for code in FUNDS.keys():
        status = get_fund_status(code)
        current_status[code] = status
        if status:
            print(f"{code} {FUNDS[code]}: 申购状态={status['sgzt']}, 最大申购={status['max_sg']}")
        else:
            print(f"{code} {FUNDS[code]}: 获取失败")

    changes = check_status_change(current_status, baseline)

    print("\n=== 检查结果 ===")
    if changes:
        print("发现状态变化:")
        for change in changes:
            print(
                "  {} {}: {} -> {} ({})".format(
                    change["code"],
                    change["name"],
                    change["old_status"],
                    change["new_status"],
                    change["change_type"],
                )
            )

        new_baseline = baseline.copy()
        for change in changes:
            new_baseline[change["code"]] = change["new_status"]
        save_baseline(new_baseline)

        result = {
            "timestamp": timestamp,
            "has_changes": True,
            "changes": changes,
        }

        title = f"基金限购状态变化 {timestamp[:10]}"
        content = build_push_text(changes, current_status, timestamp)
        send_pushplus_text(title, content)
    else:
        print("无状态变化，所有基金申购状态与基准一致")
        result = {
            "timestamp": timestamp,
            "has_changes": False,
            "current_status": {
                code: info["sgzt"] if info else "未知"
                for code, info in current_status.items()
            },
        }

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n监控执行完成")
    return result


if __name__ == "__main__":
    main()
