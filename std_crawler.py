#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全国标准信息公共服务平台爬虫
网站: https://std.samr.gov.cn/
"""

import asyncio
import json
import csv
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Page, Browser


class StdCrawler:
    """标准信息爬虫类"""

    BASE_URL = "https://std.samr.gov.cn"
    SEARCH_URL = "https://std.samr.gov.cn/search/std"

    def __init__(self, headless: bool = True, delay: float = 1.0):
        """
        初始化爬虫

        Args:
            headless: 是否无头模式运行浏览器
            delay: 请求间隔时间(秒)，避免被封
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
        # 设置超时时间
        self.page.set_default_timeout(30000)
        print("浏览器已启动")

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            print("浏览器已关闭")

    async def search(self, keyword: str, max_pages: int = 5,
                     std_type: str = "全部", std_status: str = "全部") -> list:
        """
        搜索标准

        Args:
            keyword: 搜索关键词
            max_pages: 最大爬取页数
            std_type: 标准类型 (全部/国家标准计划/国家标准/行业标准/地方标准)
            std_status: 标准状态 (全部/现行/废止)

        Returns:
            搜索结果列表
        """
        self.results = []

        # 构建搜索URL
        search_url = f"{self.SEARCH_URL}?q={keyword}"
        print(f"\n开始搜索: {keyword}")
        print(f"搜索URL: {search_url}")

        # 访问搜索页面
        await self.page.goto(search_url)
        await self.page.wait_for_load_state("networkidle")

        # 等待iframe加载
        await asyncio.sleep(2)

        # 应用筛选条件
        if std_type != "全部":
            await self._select_filter("标准类型", std_type)
        if std_status != "全部":
            await self._select_filter("标准状态", std_status)

        # 获取总结果数
        total_text = await self._get_total_count()
        print(f"找到结果: {total_text}")

        # 爬取每一页
        for page_num in range(1, max_pages + 1):
            print(f"\n--- 正在爬取第 {page_num} 页 ---")

            # 解析当前页结果
            page_results = await self._parse_search_results()

            if not page_results:
                print("没有更多结果")
                break

            self.results.extend(page_results)
            print(f"本页获取 {len(page_results)} 条记录")

            # 检查是否有下一页
            has_next = await self._has_next_page()
            if not has_next or page_num >= max_pages:
                break

            # 点击下一页
            await self._goto_next_page()

            # 随机延迟，避免被封
            delay = self.delay + random.uniform(0, 1)
            await asyncio.sleep(delay)

        print(f"\n爬取完成，共获取 {len(self.results)} 条记录")
        return self.results

    async def _select_filter(self, filter_name: str, value: str):
        """选择筛选条件"""
        try:
            # 点击对应的筛选选项
            selector = f'text="{value}"'
            await self.page.click(selector)
            await asyncio.sleep(1)
        except Exception as e:
            print(f"筛选条件设置失败: {e}")

    async def _get_total_count(self) -> str:
        """获取搜索结果总数"""
        try:
            # 等待iframe加载
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
            # 获取iframe
            iframe = self.page.frame_locator("iframe").first

            # 获取所有结果项
            items = iframe.locator("table").filter(has=iframe.locator("a[href*='Detailed']"))
            count = await items.count()

            for i in range(count):
                try:
                    item = items.nth(i)

                    # 获取标准链接和标题
                    link_element = item.locator("a[href*='Detailed']").first
                    title = await link_element.text_content()
                    href = await link_element.get_attribute("href")

                    if not title or not href:
                        continue

                    # 解析标准信息
                    result = self._parse_title(title.strip())
                    result["url"] = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    result["title"] = title.strip()

                    # 获取状态
                    try:
                        status_element = item.locator("td").last
                        status = await status_element.text_content()
                        result["status"] = status.strip() if status else ""
                    except:
                        result["status"] = ""

                    results.append(result)

                except Exception as e:
                    continue

        except Exception as e:
            print(f"解析结果出错: {e}")

        return results

    def _parse_title(self, title: str) -> dict:
        """解析标准标题，提取编号和名称"""
        parts = title.split(" ", 1)
        if len(parts) == 2:
            return {
                "std_code": parts[0],
                "std_name": parts[1]
            }
        return {
            "std_code": "",
            "std_name": title
        }

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

    async def get_detail(self, url: str) -> dict:
        """
        获取标准详情

        Args:
            url: 标准详情页URL

        Returns:
            标准详情信息
        """
        detail = {}

        try:
            await self.page.goto(url)
            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            # 获取详情页内容
            content = await self.page.content()

            # 解析基本信息
            info_items = await self.page.locator("tr").all()
            for item in info_items:
                try:
                    cells = await item.locator("td").all()
                    if len(cells) >= 2:
                        key = await cells[0].text_content()
                        value = await cells[1].text_content()
                        if key and value:
                            detail[key.strip().replace("：", "")] = value.strip()
                except:
                    continue

        except Exception as e:
            print(f"获取详情失败: {e}")

        return detail

    def save_to_csv(self, filename: str = None):
        """
        保存结果到CSV文件

        Args:
            filename: 文件名，默认使用时间戳
        """
        if not self.results:
            print("没有数据可保存")
            return

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"std_results_{timestamp}.csv"

        filepath = Path(filename)

        # 获取所有字段
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
        """
        保存结果到JSON文件

        Args:
            filename: 文件名，默认使用时间戳
        """
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
    # 创建爬虫实例
    crawler = StdCrawler(
        headless=True,   # 无头模式（不显示浏览器窗口）
        delay=1.5        # 请求间隔1.5秒
    )

    try:
        # 启动浏览器
        await crawler.start()

        # 搜索标准
        # 你可以修改以下参数：
        # - keyword: 搜索关键词
        # - max_pages: 最大爬取页数
        # - std_type: 标准类型 (全部/国家标准计划/国家标准/行业标准/地方标准)
        # - std_status: 标准状态 (全部/现行/废止)

        results = await crawler.search(
            keyword="食品安全",     # 搜索关键词
            max_pages=3,            # 爬取3页
            std_type="全部",        # 所有类型
            std_status="全部"       # 所有状态
        )

        # 打印结果预览
        print("\n=== 结果预览 ===")
        for i, result in enumerate(results[:5], 1):
            print(f"{i}. {result.get('std_code', '')} - {result.get('std_name', '')}")
            print(f"   状态: {result.get('status', '')} | URL: {result.get('url', '')}")

        if len(results) > 5:
            print(f"... 还有 {len(results) - 5} 条记录")

        # 保存结果
        crawler.save_to_csv()   # 保存为CSV
        crawler.save_to_json()  # 保存为JSON

    finally:
        # 关闭浏览器
        await crawler.close()


if __name__ == "__main__":
    # 运行爬虫
    asyncio.run(main())
