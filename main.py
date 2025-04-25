import os
import re
import aiohttp
import tomllib
import xml.etree.ElementTree as ET
import urllib.parse
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message, on_xml_message
from utils.plugin_base import PluginBase


class JDRebate(PluginBase):
    """京东商品转链返利插件"""
    description = "京东商品转链返利插件 - 自动识别京东链接并生成带返利的推广链接"
    author = "wspzf"
    version = "1.1.0"

    def __init__(self):
        super().__init__()
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")

        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)

            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", False)  # 是否启用插件
            self.appkey = basic_config.get("appkey", "")  # 折京客appkey
            self.union_id = basic_config.get("union_id", "")  # 联盟ID
            self.allowed_groups = basic_config.get("allowed_groups", [])  # 允许的群组列表
            self.signurl = basic_config.get("signurl", "5")  # signurl参数，5返回更详细信息
            self.chain_type = basic_config.get("chain_type", "2")  # chainType参数，2返回短链接
            self.show_commission = basic_config.get("show_commission", True)  # 是否显示返利金额
            
            # 修复正则表达式，使用非捕获组确保返回完整链接
            self.jd_link_pattern = r"https?://[^\s<>]*(?:3\.cn|jd\.|jingxi|u\.jd\.com)[^\s<>]+"

            # 编译正则表达式
            self.jd_link_regex = re.compile(self.jd_link_pattern)
            
            self.api_url = basic_config.get("api_url", "")  # API接口地址

            logger.success(f"京东商品转链返利插件配置加载成功")
            logger.info(f"允许的群组列表: {self.allowed_groups}")
            logger.info(f"京东链接匹配模式: {self.jd_link_pattern}")
            logger.info(f"是否显示返利金额: {self.show_commission}")
        except Exception as e:
            logger.error(f"加载京东商品转链返利插件配置失败: {str(e)}")
            self.enable = False  # 配置加载失败，禁用插件

    @on_text_message(priority=90)  # 提高优先级，确保先于其他插件处理
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息，检测并转换京东链接"""
        if not self.enable:
            logger.debug("京东转链插件未启用")
            return True  # 插件未启用，允许后续插件处理

        # 获取消息内容
        content = message.get("Content", "")
        from_user = message.get("FromWxid", "")

        logger.debug(f"京东转链插件收到文本消息: {content}")

        # 检查消息来源是否在允许的范围内
        if not await self._check_allowed_source(from_user):
            return True
        
        # 处理文本中的京东链接
        return await self._process_links_in_text(bot, from_user, content)
    
    @on_xml_message(priority=90)  # 添加对XML消息的处理
    async def handle_xml(self, bot: WechatAPIClient, message: dict):
        """处理XML消息，提取并转换京东链接"""
        if not self.enable:
            logger.debug("京东转链插件未启用")
            return True  # 插件未启用，允许后续插件处理
        
        # 获取消息内容
        content = message.get("Content", "")
        from_user = message.get("FromWxid", "")
        
        logger.debug(f"京东转链插件收到XML消息")
        
        # 检查消息来源是否在允许的范围内
        if not await self._check_allowed_source(from_user):
            return True
        
        try:
            # 解析XML内容
            root = ET.fromstring(content)
            
            # 检查是否是京东商品分享
            appmsg = root.find(".//appmsg")
            if appmsg is None:
                logger.debug("非商品分享XML消息，跳过处理")
                return True
            
            # 获取消息类型
            type_elem = appmsg.find("type")
            msg_type = type_elem.text if type_elem is not None else None
            logger.debug(f"解析到的 XML 类型: {msg_type}")
            
            # 提取商品信息的方法，根据不同类型采用不同的提取策略
            url = None
            sku = None
            
            # 提取URL路径
            url_elem = appmsg.find("url")
            if url_elem is not None:
                url = url_elem.text
            
            # 情况1: 常规URL分享
            if url and ("item.jd.com" in url or "item.m.jd.com" in url):
                logger.debug(f"从URL中提取京东商品链接: {url}")
                # 去除URL中的参数部分(问号后面的内容)
                url = self._clean_url(url)
                
            # 情况2: 京东小程序分享 (type 33)
            elif msg_type == "33" or msg_type == "36":
                logger.debug(f"检测到京东小程序分享，类型: {msg_type}")
                # 尝试从pagepath中提取SKU
                weappinfo = appmsg.find("weappinfo")
                if weappinfo is not None:
                    pagepath = weappinfo.find("pagepath")
                    if pagepath is not None and pagepath.text:
                        pagepath_text = pagepath.text
                        logger.debug(f"解析到小程序路径: {pagepath_text}")
                        
                        # 提取SKU
                        sku_match = re.search(r'sku=(\d+)', pagepath_text)
                        if sku_match:
                            sku = sku_match.group(1)
                            logger.debug(f"从小程序路径中提取到SKU: {sku}")
                            # 构建标准京东商品链接
                            url = f"https://item.jd.com/{sku}.html"
                            logger.debug(f"构建标准京东链接: {url}")
                        else:
                            logger.debug(f"无法从路径中提取SKU: {pagepath_text}")
                    else:
                        logger.debug("未找到pagepath元素或pagepath为空")
                else:
                    logger.debug("未找到weappinfo元素")
            
            # 检查是否成功提取到有效京东链接
            if url and self._is_jd_link(url):
                logger.info(f"从XML消息中提取到京东商品链接: {url}")
                
                # 转换链接
                converted_content = await self.convert_link(url)
                if converted_content:
                    # 直接发送转链结果
                    await bot.send_text_message(from_user, converted_content)
                    logger.success(f"成功发送XML转链文案到 {from_user}")
                    return False  # 阻止后续插件处理
            else:
                logger.debug(f"未能提取有效的京东链接或非京东链接")
                
        except Exception as e:
            logger.error(f"处理XML消息时出错: {str(e)}")
            
        return True
        
    async def _check_allowed_source(self, from_user: str) -> bool:
        """检查消息来源是否在允许的范围内"""
        # 检查是否是群消息
        is_group_message = from_user.endswith("@chatroom")
        
        # 如果是群消息，检查是否在允许的群组列表中
        if is_group_message and self.allowed_groups and from_user not in self.allowed_groups:
            logger.debug(f"群组 {from_user} 不在允许列表中，不处理")
            return False
        else:
            logger.debug(f"消息来源 {from_user} 允许处理")
            return True
    
    def _is_jd_link(self, url: str) -> bool:
        """检查是否是京东链接"""
        return bool(self.jd_link_regex.match(url))
    
    def _clean_url(self, url: str) -> str:
        """清理URL，去除参数部分"""
        if "?" in url:
            return url.split("?")[0]
        return url
        
    async def _process_links_in_text(self, bot: WechatAPIClient, from_user: str, content: str) -> bool:
        """处理文本中的京东链接"""
        # 使用正则表达式查找所有匹配的京东链接
        jd_links = self.jd_link_regex.findall(content)
        
        # 另一种方法：如果上面的findall仍然只返回部分匹配，则使用finditer
        if not jd_links or (len(jd_links) == 1 and len(jd_links[0]) < 10):
            logger.debug("使用findall失败，尝试使用finditer匹配")
            jd_links = []
            for match in self.jd_link_regex.finditer(content):
                jd_links.append(match.group(0))
                
        logger.debug(f"检测到原始链接: {jd_links}")
        
        # 过滤无效链接并清理URL
        valid_links = []
        for link in jd_links:
            if len(link) > 12 and ('http' in link or 'jd.com' in link or 'u.jd.com' in link):
                # 清理URL，去除参数部分
                clean_link = self._clean_url(link)
                valid_links.append(clean_link)
                # 记录原始链接和清理后的链接，用于后续替换
                if clean_link != link:
                    logger.debug(f"清理链接: {link} -> {clean_link}")
        
        logger.debug(f"过滤后的有效链接: {valid_links}")
        
        if not valid_links:
            logger.debug("没有找到有效的京东链接，不处理")
            return True  # 没有找到京东链接，允许后续插件处理
        
        logger.info(f"检测到{len(valid_links)}个京东链接，准备转链")
        
        # 处理链接
        if len(valid_links) == 1:
            # 只有一个链接，直接返回转链后的文案
            logger.debug(f"处理单个链接: {valid_links[0]}")
            converted_content = await self.convert_link(valid_links[0])
            if converted_content:
                await bot.send_text_message(from_user, converted_content)
                logger.success(f"成功发送转链文案到 {from_user}")
                return False  # 阻止后续插件处理
        else:
            # 有多个链接，替换原消息中的每个链接
            logger.debug(f"处理多个链接: {valid_links}")
            replaced_content = content
            has_conversion = False
            
            # 创建原始链接到清理后链接的映射
            link_map = {}
            for link in jd_links:
                clean_link = self._clean_url(link)
                if len(clean_link) > 12 and ('http' in clean_link or 'jd.com' in clean_link or 'u.jd.com' in clean_link):
                    link_map[link] = clean_link
            
            # 处理每个清理后的链接
            for original_link, clean_link in link_map.items():
                result = await self.convert_link_official(clean_link)
                logger.debug(f"链接 {clean_link} 转换结果: {result}")
                if result:
                    # 替换原消息中的原始链接为转链后的链接
                    replaced_content = replaced_content.replace(original_link, result)
                    has_conversion = True
            
            if has_conversion:
                await bot.send_text_message(from_user, replaced_content)
                logger.success(f"成功发送多链接转链结果到 {from_user}")
                return False  # 阻止后续插件处理
                
        return True  # 允许后续插件处理
    
    async def convert_link(self, link: str) -> Optional[str]:
        """使用折京客API转换链接，返回转链后的完整文案"""
        try:
            logger.debug(f"开始转换链接: {link}")
            # URL编码链接
            encoded_link = urllib.parse.quote(link)
            
            async with aiohttp.ClientSession() as session:
                params = {
                    "appkey": self.appkey,
                    "materialId": encoded_link,
                    "unionId": self.union_id,
                    "chainType": self.chain_type,
                    "signurl": self.signurl
                }
                
                logger.debug(f"请求参数: {params}")
                
                # 添加请求头
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                }
                
                # 发送GET请求
                async with session.get(self.api_url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"转链API请求失败: {response.status}")
                        return None
                        
                    # 尝试读取响应内容
                    try:
                        text = await response.text()
                        import json
                        result = json.loads(text)
                        logger.debug(f"API返回结果: {result}")
                    except Exception as e:
                        logger.error(f"解析API响应失败: {str(e)}")
                        return None
            
            # 检查返回结果
            if "status" not in result or result["status"] != 200 or "content" not in result or not result["content"]:
                logger.warning("API返回无效结果")
                return None
            
            # 获取第一个商品信息
            content_items = result["content"]
            if not content_items:
                logger.warning("API返回的商品列表为空")
                return None
                
            item = content_items[0]
            
            # 提取商品信息
            title = item.get("title", "")
            original_price = item.get("size", "")  # 原价
            quanhou_jiage = item.get("quanhou_jiage", "")  # 券后价
            coupon_info = item.get("coupon_info", "")  # 优惠券描述
            coupon_amount = item.get("coupon_info_money", "")  # 优惠券金额
            commission = item.get("tkfee3", "")  # 佣金金额
            shorturl = item.get("shorturl", "")  # 短链接
            
            logger.debug(f"商品信息提取成功: 标题={title}, 价格={quanhou_jiage}, 短链接={shorturl}")
            
            if not shorturl:
                logger.warning("API返回结果中无短链接")
                return None
            
            # 构建简化版的转链文案
            formatted_content = f"📌 {title}\n"
            
            # 添加价格信息
            if original_price and quanhou_jiage and original_price != quanhou_jiage:
                formatted_content += f"💰 原价: ¥{original_price} 券后价: ¥{quanhou_jiage}\n"
            elif quanhou_jiage:
                formatted_content += f"💰 价格: ¥{quanhou_jiage}\n"
            
            # 添加优惠券信息
            if coupon_info:
                formatted_content += f"🎁 优惠: {coupon_info}\n"
            elif coupon_amount and coupon_amount != "0":
                formatted_content += f"🎁 优惠券: ¥{coupon_amount}\n"
            
            # 添加佣金信息
            if commission and commission != "0" and self.show_commission:
                formatted_content += f"💸 返利: ¥{commission}\n"
            
            # 添加购买链接
            formatted_content += f"👉 购买链接: {shorturl}"
            
            return formatted_content
            
        except Exception as e:
            logger.error(f"转链过程中发生错误: {str(e)}")
            return None
    
    async def convert_link_official(self, link: str) -> Optional[str]:
        """使用折京客API转换链接，只返回短链接"""
        try:
            logger.debug(f"开始转换链接(官方): {link}")
            # URL编码链接
            encoded_link = urllib.parse.quote(link)
            
            async with aiohttp.ClientSession() as session:
                params = {
                    "appkey": self.appkey,
                    "materialId": encoded_link,
                    "unionId": self.union_id,
                    "chainType": self.chain_type,
                    "signurl": self.signurl
                }
                
                logger.debug(f"请求参数: {params}")
                
                # 添加请求头
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                }
                
                # 发送GET请求
                async with session.get(self.api_url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"转链API请求失败: {response.status}")
                        return None
                        
                    # 尝试读取响应内容
                    try:
                        text = await response.text()
                        import json
                        result = json.loads(text)
                    except Exception as e:
                        logger.error(f"解析API响应失败: {str(e)}")
                        return None
                
                # 检查返回结果
                if "status" not in result or result["status"] != 200 or "content" not in result or not result["content"]:
                    logger.warning("API返回无效结果")
                    return None
                
                # 获取第一个商品信息
                content_items = result["content"]
                if not content_items:
                    logger.warning("API返回的商品列表为空")
                    return None
                    
                item = content_items[0]
                
                # 依次尝试获取短链接、优惠券链接、商品链接
                shorturl = item.get("shorturl", "")
                if shorturl:
                    return shorturl
                
                coupon_click_url = item.get("coupon_click_url", "")
                if coupon_click_url:
                    return coupon_click_url
                
                item_url = item.get("item_url", "")
                if item_url:
                    return item_url
                
                logger.warning("API返回结果中无有效链接")
            return None
                
        except Exception as e:
            logger.error(f"转链过程中发生错误: {str(e)}")
            return None 