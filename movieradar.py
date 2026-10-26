import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def request_json(request, label):
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except Exception:
        # 不输出请求地址或原始异常，避免泄露密钥。
        sys.exit(f"{label}未完成，请检查服务状态和仓库机密。")

    if not isinstance(data, dict):
        sys.exit(f"{label}返回的数据格式异常。")

    return data


def clean_text(value):
    return " ".join((value or "").split())


def format_title(item):
    local_title = clean_text(item.get("title") or item.get("name"))
    original_title = clean_text(
        item.get("original_title") or item.get("original_name")
    )

    if local_title and original_title:
        if local_title.casefold() != original_title.casefold():
            return f"{local_title} / {original_title}"

    return local_title or original_title or "暂无名称"


def format_item(item, kind, date_field):
    title = format_title(item)
    release_date = item.get(date_field) or "日期待定"

    if item.get("vote_count", 0) > 0:
        rating = f"{item.get('vote_average', 0):.1f}/10"
    else:
        rating = "暂无评分"

    overview = clean_text(item.get("overview")) or "暂无中文简介。"
    if len(overview) > 100:
        overview = overview[:100] + "…"

    link = f"https://www.themoviedb.org/{kind}/{item['id']}"

    return (
        f"### {title}\n\n"
        f"日期：{release_date} ｜ TMDB：{rating}\n\n"
        f"{overview}\n\n"
        f"[查看详情]({link})"
    )


def discover(config, token, kind, date_filter, start, end):
    params = {
        "language": config["language"],
        "with_origin_country": "|".join(config["origin_countries"]),
        "include_adult": "false",
        "sort_by": "popularity.desc",
        f"{date_filter}.gte": str(start),
        f"{date_filter}.lte": str(end),
        "page": 1,
    }

    url = (
        f"https://api.themoviedb.org/3/discover/{kind}?"
        + urllib.parse.urlencode(params)
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
        },
    )

    data = request_json(request, "获取影视资料")
    if not isinstance(data.get("results"), list):
        sys.exit("TMDB 返回的数据格式异常，未发送日报。")

    return data["results"]


def send_wechat(sendkey, today, message):
    body = urllib.parse.urlencode({
        "title": f"MovieRadar 新片新剧 · {today}",
        "desp": message,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://sctapi.ftqq.com/" + sendkey + ".send",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    result = request_json(
        request,
        "微信推送请求（请先查看微信是否已经收到，避免重复发送）",
    )
    if result.get("code") != 0:
        sys.exit("推送服务未确认成功，请查看 Server酱推送日志。")

    print("推送服务已接受日报，请查看微信。")


def main():
    config_path = Path(__file__).with_name("config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    token = os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip()
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()

    if not token or not sendkey:
        sys.exit("缺少 TMDB_READ_ACCESS_TOKEN 或 SERVERCHAN_SENDKEY。")
    if not sendkey.startswith("SCT"):
        sys.exit("请使用以 SCT 开头的 Server酱 Turbo SendKey。")

    today = datetime.now(ZoneInfo(config["timezone"])).date()
    past_days = int(config["past_days"])
    future_days = int(config["future_days"])
    limit = int(config["max_items_per_section"])

    if past_days < 1 or future_days < 1:
        sys.exit("配置中的天数必须大于零。")
    if not 1 <= limit <= 10:
        sys.exit("每栏作品数量必须在 1 到 10 之间。")
    if not config["origin_countries"]:
        sys.exit("请在 config.json 中设置关注的国家或地区。")

    # 近期包含今天；未来从明天开始，两个栏目不重叠。
    periods = [
        (
            "近期已上",
            today - timedelta(days=past_days - 1),
            today,
        ),
        (
            "即将上映／开播",
            today + timedelta(days=1),
            today + timedelta(days=future_days),
        ),
    ]

    kinds = []
    if config.get("include_movies"):
        kinds.append(
            ("movie", "电影", "primary_release_date", "release_date")
        )
    if config.get("include_tv"):
        kinds.append(
            ("tv", "新剧", "first_air_date", "first_air_date")
        )
    if not kinds:
        sys.exit("请在配置中至少开启电影或电视剧。")

    sections = [
        f"# MovieRadar · {today}",
        (
            "名称优先显示中文名 / 原文名；名称相同时只显示一次。"
            "中文译名缺失时显示可用名称。\n\n"
            "日期采用 TMDB 收录的电影主要上映日期或新剧首次开播日期，"
            "不代表国内视频平台上线时间。\n\n"
            f"按热度选取，每栏最多 {limit} 部。"
            "窗口内的作品可能连续几天重复出现。"
        ),
    ]

    for period_name, start, end in periods:
        for kind, kind_name, date_filter, date_field in kinds:
            items = discover(
                config, token, kind, date_filter, start, end
            )

            lines = [
                f"## {period_name} · {kind_name}",
                f"{start} 至 {end}",
            ]

            if not items:
                lines.append("本次未找到符合条件的作品。")

            for item in items[:limit]:
                lines.append(format_item(item, kind, date_field))

            sections.append("\n\n".join(lines))

    sections.append(
        "资料来源：TMDB。本项目使用 TMDB API，"
        "但未经 TMDB 认可或认证。"
    )

    message = "\n\n".join(sections)
    print(message)
    send_wechat(sendkey, today, message)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(
            "程序未完成，请检查 config.json 内容及程序文件是否完整。"
        )
