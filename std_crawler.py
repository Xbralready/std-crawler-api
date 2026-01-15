#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全国标准信息公共服务平台爬虫 v2.0
新增功能：详情获取、PDF下载链接、批量搜索
"""

import asyncio
import json
import csv
import re
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from playwright.async_api import async_playwright, Page, Browser


class StdCrawler:
    """标准信息爬虫类"""

    BASE_URL = "https://std.samr.gov.cn"
    SEARCH_URL = "https://std.samr.gov.cn/search/std"
    OPENSTD_URL = "https://openstd.samr.gov.cn"

    def __init__(self, headless: bool = True, delay: float = 1.0):
        """
        初始化爬虫
        """
        self.headless = headless
        self.delay = delay
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.results = []

    async def start(self):
        """启动浏览器"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()
        self.page.set_default_timeout(60000)  # 增加到60秒
        print("浏览器已启动")

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            print("浏览器已关闭")

    async def batch_search(self, keywords: List[str], max_pages: int = 3,
                           std_type: str = "全部", std_status: str = "全部",
                           get_details: bool = False) -> List[Dict]:
        """
        批量搜索多个关键词
        """
        all_results = []

        for i, keyword in enumerate(keywords):
            print(f"\n[{i+1}/{len(keywords)}] 搜索关键词: {keyword}")
            results = await self.search(
                keyword=keyword,
                max_pages=max_pages,
                std_type=std_type,
                std_status=std_status
            )

            if get_details and results:
                # 限制详情获取数量，避免过多请求
                max_details = min(len(results), 20)
                print(f"正在获取 {max_details} 条记录的详情（共 {len(results)} 条）...")
                for j, result in enumerate(results[:max_details]):
                    if result.get("url"):
                        print(f"  [{j+1}/{max_details}] 获取详情: {result.get('std_code', '')}")
                        detail = await self.get_detail(result["url"])
                        result.update(detail)
                        # 增加延迟避免被限流
                        await asyncio.sleep(self.delay + random.uniform(0.5, 1.5))

            for result in results:
                result["search_keyword"] = keyword

            all_results.extend(results)

            if i < len(keywords) - 1:
                await asyncio.sleep(self.delay)

        self.results = all_results
        print(f"\n批量搜索完成，共获取 {len(all_results)} 条记录")
        return all_results

    async def search(self, keyword: str, max_pages: int = 5,
                     std_type: str = "全部", std_status: str = "全部") -> list:
        """搜索标准"""
        self.results = []

        search_url = f"{self.SEARCH_URL}?q={keyword}"
        print(f"\n开始搜索: {keyword}")

        await self.page.goto(search_url)
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        if std_type != "全部":
            await self._select_filter("标准类型", std_type)
        if std_status != "全部":
            await self._select_filter("标准状态", std_status)

        total_text = await self._get_total_count()
        print(f"找到结果: {total_text}")

        for page_num in range(1, max_pages + 1):
            print(f"\n--- 正在爬取第 {page_num} 页 ---")

            page_results = await self._parse_search_results()

            if not page_results:
                print("没有更多结果")
                break

            self.results.extend(page_results)
            print(f"本页获取 {len(page_results)} 条记录")

            has_next = await self._has_next_page()
            if not has_next or page_num >= max_pages:
                break

            await self._goto_next_page()
            delay = self.delay + random.uniform(0, 1)
            await asyncio.sleep(delay)

        print(f"\n爬取完成，共获取 {len(self.results)} 条记录")
        return self.results

    async def _select_filter(self, filter_name: str, value: str):
        """选择筛选条件"""
        try:
            selector = f'text="{value}"'
            await self.page.click(selector)
            await asyncio.sleep(1)
        except Exception as e:
            print(f"筛选条件设置失败: {e}")

    async def _get_total_count(self) -> str:
        """获取搜索结果总数"""
        try:
            iframe = self.page.frame_locator("iframe").first
            total_element = iframe.locator("text=为您找到相关结果约")
            text = await total_element.text_content()
            return text if text else "未知"
        except Exception:
            return "未知"

    async def _parse_search_results(self) -> list:
        """解析搜索结果"""
        results = []

        try:
            iframe = self.page.frame_locator("iframe").first
            items = iframe.locator("table").filter(has=iframe.locator("a[href*='Detailed']"))
            count = await items.count()

            for i in range(count):
                try:
                    item = items.nth(i)

                    link_element = item.locator("a[href*='Detailed']").first
                    title = await link_element.text_content()
                    href = await link_element.get_attribute("href")

                    if not title or not href:
                        continue

                    result = self._parse_title(title.strip())
                    result["url"] = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    result["title"] = title.strip()

                    try:
                        status_element = item.locator("td").last
                        status = await status_element.text_content()
                        result["status"] = status.strip() if status else ""
                    except:
                        result["status"] = ""

                    results.append(result)

                except Exception:
                    continue

        except Exception as e:
            print(f"解析结果出错: {e}")

        return results

    def _parse_title(self, title: str) -> dict:
        """解析标准标题"""
        title = re.sub(r'\s+', ' ', title).strip()
        parts = title.split(" ", 1)
        if len(parts) == 2:
            return {"std_code": parts[0], "std_name": parts[1]}
        return {"std_code": "", "std_name": title}

    async def _has_next_page(self) -> bool:
        """检查是否有下一页"""
        try:
            iframe = self.page.frame_locator("iframe").first
            next_btn = iframe.locator("text=下一页")
            return await next_btn.count() > 0
        except:
            return False

    async def _goto_next_page(self):
        """跳转到下一页"""
        try:
            iframe = self.page.frame_locator("iframe").first
            next_btn = iframe.locator("text=下一页")
            await next_btn.click()
            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"翻页失败: {e}")

    async def get_detail(self, url: str, retry_count: int = 2) -> dict:
        """获取标准详情，支持重试"""
        detail = {}

        for attempt in range(retry_count + 1):
            try:
                # 使用较长超时，只等待domcontentloaded而非完整加载
                await self.page.goto(url, timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(2)  # 等待页面渲染

                # 获取标准名称
                try:
                    cn_title = await self.page.locator("h4").first.text_content(timeout=5000)
                    detail["cn_title"] = cn_title.strip() if cn_title else ""
                except:
                    pass

                try:
                    en_title = await self.page.locator("h5").first.text_content(timeout=5000)
                    detail["en_title"] = en_title.strip() if en_title else ""
                except:
                    pass

                # 获取基础信息
                try:
                    terms = await self.page.locator("dt").all()
                    definitions = await self.page.locator("dd").all()

                    for i, term in enumerate(terms):
                        if i < len(definitions):
                            key = await term.text_content(timeout=3000)
                            value = await definitions[i].text_content(timeout=3000)
                            if key and value:
                                key = key.strip().replace("：", "").replace(":", "")
                                value = value.strip()
                                detail[key] = value
                except:
                    pass

                # 获取起草单位
                try:
                    paragraph = await self.page.locator("p:has-text('主要起草单位')").text_content(timeout=5000)
                    if paragraph:
                        units = paragraph.replace("主要起草单位", "").strip()
                        detail["起草单位"] = units
                except:
                    pass

                # 获取起草人
                try:
                    paragraph = await self.page.locator("p:has-text('主要起草人')").text_content(timeout=5000)
                    if paragraph:
                        persons = paragraph.replace("主要起草人", "").strip()
                        detail["起草人"] = persons
                except:
                    pass

                # 只有成功获取到基本信息才尝试获取PDF链接
                if detail.get("cn_title") or detail.get("标准号"):
                    try:
                        pdf_info = await self._get_pdf_link()
                        if pdf_info:
                            detail.update(pdf_info)
                    except Exception as e:
                        print(f"获取PDF链接失败: {e}")

                # 成功获取，跳出重试循环
                if detail:
                    break

            except Exception as e:
                print(f"获取详情失败 (尝试 {attempt + 1}/{retry_count + 1}): {e}")
                if attempt < retry_count:
                    wait_time = (attempt + 1) * 3  # 递增等待时间
                    print(f"等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)

        return detail

    async def _get_pdf_link(self) -> dict:
        """获取标准PDF下载链接"""
        pdf_info = {}

        try:
            view_text_btn = self.page.locator("text=查看文本").first
            if await view_text_btn.count() > 0:
                async with self.page.context.expect_page() as new_page_info:
                    await view_text_btn.click()
                    await asyncio.sleep(2)

                try:
                    new_page = await new_page_info.value
                    await new_page.wait_for_load_state("networkidle")

                    pdf_page_url = new_page.url
                    pdf_info["pdf_page_url"] = pdf_page_url

                    download_btn = new_page.locator("button:has-text('下载标准')")
                    if await download_btn.count() > 0:
                        pdf_info["has_pdf_download"] = True

                    preview_btn = new_page.locator("button:has-text('在线预览')")
                    if await preview_btn.count() > 0:
                        pdf_info["has_online_preview"] = True

                    hcno_match = re.search(r'hcno=([A-F0-9]+)', pdf_page_url)
                    if hcno_match:
                        hcno = hcno_match.group(1)
                        pdf_info["hcno"] = hcno
                        pdf_info["pdf_download_url"] = f"https://openstd.samr.gov.cn/bzgk/std/downLoadView?hcno={hcno}"

                    await new_page.close()
                except:
                    pass

        except Exception:
            pass

        return pdf_info

    def save_to_csv(self, filename: str = None):
        """保存结果到CSV文件"""
        if not self.results:
            print("没有数据可保存")
            return

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"std_results_{timestamp}.csv"

        filepath = Path(filename)

        fieldnames = set()
        for result in self.results:
            fieldnames.update(result.keys())
        fieldnames = sorted(list(fieldnames))

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.results)

        print(f"数据已保存到: {filepath.absolute()}")

    def save_to_json(self, filename: str = None):
        """保存结果到JSON文件"""
        if not self.results:
            print("没有数据可保存")
            return

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"std_results_{timestamp}.json"

        filepath = Path(filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        print(f"数据已保存到: {filepath.absolute()}")


async def main():
    """主函数 - 使用示例"""
    crawler = StdCrawler(headless=True, delay=1.5)

    try:
        await crawler.start()

        # 批量搜索多个关键词
        keywords = ["安全生产", "接地标准"]
        results = await crawler.batch_search(
            keywords=keywords,
            max_pages=2,
            get_details=True
        )

        print("\n=== 结果预览 ===")
        for i, result in enumerate(results[:5], 1):
            print(f"{i}. {result.get('std_code', '')} - {result.get('std_name', '')}")
            print(f"   状态: {result.get('status', '')} | 关键词: {result.get('search_keyword', '')}")
            if result.get('pdf_page_url'):
                print(f"   PDF页面: {result.get('pdf_page_url', '')}")

        crawler.save_to_csv()
        crawler.save_to_json()

    finally:
        await crawler.close()


if __name__ == "__main__":
    asyncio.run(main())
