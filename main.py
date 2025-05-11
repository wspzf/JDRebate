import os
import re
import json
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
    version = "1.2.0"

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
            self.group_mode = basic_config.get("group_mode", "all")  # 新增：群组控制模式，默认为 "all"
            self.group_list = basic_config.get("group_list", [])  # 新增：群组/用户列表
            self.signurl = basic_config.get("signurl", "5")  # signurl参数，5返回更详细信息
            self.chain_type = basic_config.get("chain_type", "2")  # chainType参数，2返回短链接
            self.show_commission = basic_config.get("show_commission", True)  # 是否显示返利金额
            
            # 修复正则表达式，使用非捕获组确保返回完整链接
            self.jd_link_pattern = r"https?://[^\s<>]*(?:3\.cn|jd\.|jingxi|u\.jd\.com)[^\s<>]+"

            # 编译正则表达式
            self.jd_link_regex = re.compile(self.jd_link_pattern)
            
            self.api_url = "http://api.zhetaoke.com:20000/api/open_jing_union_open_promotion_byunionid_get.ashx" # 直接写入 api_url

            logger.success(f"京东商品转链返利插件配置加载成功")
            logger.info(f"群组控制模式: {self.group_mode}")
            logger.info(f"群组/用户列表: {self.group_list}")
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
        # 检查消息来源是否为私聊或群聊
        is_group_message = from_user.endswith("@chatroom")
        
        if self.group_mode == "all":
            logger.debug(f"群组控制模式为 'all'，允许来自 {from_user} 的消息")
            return True
        elif self.group_mode == "whitelist":
            if from_user in self.group_list:
                logger.debug(f"群组控制模式为 'whitelist'，{from_user} 在白名单中，允许处理")
                return True
            else:
                logger.debug(f"群组控制模式为 'whitelist'，{from_user} 不在白名单中，不处理")
                return False
        elif self.group_mode == "blacklist":
            if from_user in self.group_list:
                logger.debug(f"群组控制模式为 'blacklist'，{from_user} 在黑名单中，不处理")
                return False
            else:
                logger.debug(f"群组控制模式为 'blacklist'，{from_user} 不在黑名单中，允许处理")
                return True
        else:
            logger.warning(f"未知的群组控制模式: {self.group_mode}，默认允许所有来源")
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
    
    async def _parse_api_response(self, api_json_result: dict) -> Optional[Dict[str, Any]]:
        """
        Parses the API JSON response, attempting to handle two known structures.
        Returns a dictionary with extracted data or None if parsing fails or data is invalid.
        """
        try:
            # Attempt to parse Structure 1 (nested, e.g., jd_union_open_promotion_byunionid_get_response)
            if "jd_union_open_promotion_byunionid_get_response" in api_json_result:
                response_data = api_json_result.get("jd_union_open_promotion_byunionid_get_response", {})
                outer_code = response_data.get("code")
                if outer_code == "0": #京东联盟外层code，0表示成功
                    result_str = response_data.get("result")
                    if result_str and isinstance(result_str, str):
                        try:
                            inner_result = json.loads(result_str) # 'result' is a JSON string
                            inner_code = inner_result.get("code") # 折京客内层code
                            if inner_code == 200: # 200表示成功
                                data_payload = inner_result.get("data", {})
                                if data_payload and isinstance(data_payload, dict) :
                                    short_url = data_payload.get("shortURL")
                                    click_url = data_payload.get("clickURL") # clickURL is also in this structure
                                    if short_url:
                                        return {
                                            "shorturl": short_url,
                                            "clickURL": click_url, # Capture clickURL if present
                                            "_is_minimal": True # Indicates less detailed data
                                        }
                                    else:
                                        logger.warning("API (Structure 1) did not return shortURL in data payload.")
                                else:
                                    logger.warning(f"API (Structure 1) 'data' payload is missing or not a dict. Inner result: {inner_result}")
                            else:
                                logger.warning(f"API (Structure 1) inner code: {inner_code}, message: {inner_result.get('message')}. RequestId: {inner_result.get('requestId')}")
                        except json.JSONDecodeError as e:
                            logger.error(f"API (Structure 1) failed to parse inner JSON 'result': {e}. Result string: '{result_str[:200]}...'")
                    else:
                        logger.warning(f"API (Structure 1) 'result' string not found or not a string. Response data: {str(response_data)[:200]}")
                else:
                    logger.warning(f"API (Structure 1) outer_code: {outer_code}. Full response: {str(response_data)[:500]}")
                return None # Failed to process structure 1 correctly or outer_code indicated error

            # Attempt to parse Structure 2 (flat, with "status" and "content")
            elif "status" in api_json_result and api_json_result.get("status") == 200:
                content_items = api_json_result.get("content")
                if content_items and isinstance(content_items, list) and len(content_items) > 0:
                    item = content_items[0]
                    # This structure typically contains full details
                    return {
                        "title": item.get("title", ""),
                        "original_price": item.get("size", ""),
                        "quanhou_jiage": item.get("quanhou_jiage", ""),
                        "coupon_info": item.get("coupon_info", ""),
                        "coupon_amount": item.get("coupon_info_money", ""),
                        "commission": item.get("tkfee3", ""),
                        "shorturl": item.get("shorturl", ""),
                        "coupon_click_url": item.get("coupon_click_url", ""),
                        "item_url": item.get("item_url", ""),
                        "_is_minimal": False
                    }
                else:
                    # Handle cases like {"status":200,"message":"succ","data":null,"cid":"xxxxx"}
                    if api_json_result.get("data") is None and api_json_result.get("message"):
                        logger.warning(f"API (Structure 2 like) 'content' was empty or invalid, message: {api_json_result.get('message')}")
                    else:
                        logger.warning("API (Structure 2) 'content' is empty or not a list.")
            
            # If neither structure matched or a non-200 status for structure 2
            else:
                logger.warning(f"API response did not match known structures or indicated an error. Status: {api_json_result.get('status')}. Raw: {str(api_json_result)[:500]}")

        except Exception as e:
            logger.error(f"Unexpected error during API response parsing: {e}. Raw response: {str(api_json_result)[:500]}")
        
        return None
    
    async def convert_link(self, link: str) -> Optional[str]:
        """使用折京客API转换链接，返回转链后的完整文案"""
        try:
            logger.debug(f"开始转换链接 (convert_link): {link}")
            encoded_link = urllib.parse.quote(link)
            
            async with aiohttp.ClientSession() as session:
                params = {
                    "appkey": self.appkey,
                    "materialId": encoded_link,
                    "unionId": self.union_id,
                    "chainType": self.chain_type,
                    "signurl": self.signurl
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded", # Keep as is, GET uses params in URL
                    "Accept": "application/json"
                }
                logger.debug(f"请求参数 (convert_link): {params}")
                async with session.get(self.api_url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"转链API请求失败 (convert_link): {response.status}, Response: {await response.text()}")
                        return None
                    try:
                        text = await response.text()
                        api_json_result = json.loads(text) # Parse the JSON text
                        logger.debug(f"API返回原始结果 (convert_link): {str(api_json_result)[:1000]}") # Log raw for debug
                    except json.JSONDecodeError as e:
                        logger.error(f"解析API响应JSON失败 (convert_link): {e}. Response text: {text[:500]}")
                        return None
            
            parsed_data = await self._parse_api_response(api_json_result)

            if not parsed_data:
                logger.warning("convert_link: _parse_api_response returned None.")
                return None

            shorturl = parsed_data.get("shorturl")
            if not shorturl:
                logger.warning("convert_link: Parsed API data does not contain a short URL.")
                return None

            if parsed_data.get("_is_minimal"):
                logger.info(f"API for '{link}' returned minimal data. Sending simplified message with URL: {shorturl}")
                return f"📌 京东推广链接\n👉 {shorturl}"

            # Build the rich message using data from parsed_data
            title = parsed_data.get("title", "京东商品") # Default title if empty
            original_price = parsed_data.get("original_price", "")
            quanhou_jiage = parsed_data.get("quanhou_jiage", "")
            coupon_info = parsed_data.get("coupon_info", "")
            coupon_amount = parsed_data.get("coupon_amount", "")
            commission = parsed_data.get("commission", "")
            
            formatted_content = f"📌 {title or '京东商品'}\n" # Ensure title is not empty
            
            if quanhou_jiage: # Primary price to show
                price_info = f"💰 价格: ¥{quanhou_jiage}"
                if original_price and original_price != quanhou_jiage:
                    price_info = f"💰 原价: ¥{original_price} 券后: ¥{quanhou_jiage}"
                formatted_content += f"{price_info}\n"
            elif original_price: # Fallback if only original price
                 formatted_content += f"💰 价格: ¥{original_price}\n"

            if coupon_info:
                formatted_content += f"🎁 优惠: {coupon_info}\n"
            elif coupon_amount and coupon_amount != "0":
                formatted_content += f"🎁 优惠券: ¥{coupon_amount}\n"
            
            if self.show_commission and commission and commission != "0":
                formatted_content += f"💸 返利: ¥{commission}\n"
            
            formatted_content += f"👉 购买链接: {shorturl}"
            
            return formatted_content
            
        except Exception as e:
            logger.error(f"转链过程中发生错误 (convert_link for {link}): {str(e)}")
            return None
    
    async def convert_link_official(self, link: str) -> Optional[str]:
        """使用折京客API转换链接，只返回短链接或最优先的可用链接"""
        try:
            logger.debug(f"开始转换链接 (official): {link}")
            encoded_link = urllib.parse.quote(link)
            
            async with aiohttp.ClientSession() as session:
                params = {
                    "appkey": self.appkey,
                    "materialId": encoded_link,
                    "unionId": self.union_id,
                    "chainType": self.chain_type,
                    "signurl": self.signurl
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json"
                }
                logger.debug(f"请求参数 (official): {params}")
                async with session.get(self.api_url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"转链API请求失败 (official): {response.status}, Response: {await response.text()}")
                        return None
                    try:
                        text = await response.text()
                        api_json_result = json.loads(text)
                        logger.debug(f"API返回原始结果 (official): {str(api_json_result)[:1000]}")
                    except json.JSONDecodeError as e:
                        logger.error(f"解析API响应JSON失败 (official): {e}. Response text: {text[:500]}")
                        return None
                
            parsed_data = await self._parse_api_response(api_json_result)

            if not parsed_data:
                logger.warning("convert_link_official: _parse_api_response returned None.")
                return None

            # Priority: shorturl, then clickURL (from minimal), then coupon_click_url/item_url (from full)
            if parsed_data.get("shorturl"):
                return parsed_data.get("shorturl")
            
            if parsed_data.get("_is_minimal") and parsed_data.get("clickURL"):
                logger.debug("convert_link_official: Using clickURL as fallback for minimal response.")
                return parsed_data.get("clickURL")
            
            if not parsed_data.get("_is_minimal"): # Rich data structure
                if parsed_data.get("coupon_click_url"):
                    logger.debug("convert_link_official: Using coupon_click_url as fallback.")
                    return parsed_data.get("coupon_click_url")
                if parsed_data.get("item_url"):
                    logger.debug("convert_link_official: Using item_url as fallback.")
                    return parsed_data.get("item_url")
            
            logger.warning(f"convert_link_official: Parsed API data for {link} did not contain any usable URL.")
            return None
                
        except Exception as e:
            logger.error(f"转链过程中发生错误 (official for {link}): {str(e)}")
            return None 