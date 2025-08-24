import asyncio
import os
import re
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from deepgram import (
    DeepgramClient,
    PrerecordedOptions,
)

load_dotenv()
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')

def get_itunes_id(apple_podcast_url):
    # 從 Apple Podcast URL 提取 ID
    match = re.search(r'id(\d+)', apple_podcast_url)
    if not match:
        raise ValueError("無法從 URL 提取 podcast ID")
    return match.group(1)

def get_rss_feed(itunes_id):
    # 使用 iTunes API 獲取 RSS feed URL
    lookup_url = f'https://itunes.apple.com/lookup?id={itunes_id}'
    response = requests.get(lookup_url)
    data = response.json()
    
    if not data.get('results'):
        raise ValueError("找不到此 podcast 的資訊")
        
    return data['results'][0].get('feedUrl')

def get_episode_url(rss_feed_url, episode_id=None):
    """從 RSS feed 獲取音訊 URL、頻道名稱和單集標題"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
    }
    response = requests.get(rss_feed_url, headers=headers)
    root = ET.fromstring(response.content)
    
    # 獲取頻道名稱
    channel = root.find('channel')
    channel_title = "Unknown_Channel"
    if channel is not None:
        title_element = channel.find('title')
        if title_element is not None:
            channel_title = title_element.text
            print(f"Podcast標題: {channel_title}")
    
    # 如果有指定 episode_id，尋找對應的集數
    if episode_id:
        print(f"正在尋找episode_id: {episode_id}")
        for item in root.findall('.//item'):
            # 檢查多個可能的標籤
            possible_tags = ['guid', 'id', 'link', 'enclosure']
            for tag in possible_tags:
                element = item.find(tag)
                if element is not None:
                    # 對於 enclosure，檢查 url 屬性
                    if tag == 'enclosure':
                        url = element.get('url', '')
                        print(f"檢查enclosure URL: {url}")
                        if episode_id in url:
                            print(f"找到匹配的URL: {url}")
                            # 獲取單集標題
                            episode_title_element = item.find('title')
                            episode_title = episode_title_element.text if episode_title_element is not None else "Unknown_Episode"
                            return url, channel_title, episode_title
                    # 對於其他標籤，檢查文字內容
                    elif element.text and episode_id in element.text:
                        print(f"在{tag}中找到匹配: {element.text}")
                        enclosure = item.find('enclosure')
                        if enclosure is not None:
                            url = enclosure.get('url')
                            print(f"找到匹配的URL: {url}")
                            # 獲取單集標題
                            episode_title_element = item.find('title')
                            episode_title = episode_title_element.text if episode_title_element is not None else "Unknown_Episode"
                            return url, channel_title, episode_title
        
        # 如果找不到指定的集數，拋出錯誤而不是使用最新一集
        raise ValueError(f"找不到指定的集數 ID: {episode_id}")
    
    # 如果沒有指定 episode_id，返回最新一集
    latest_item = root.find('.//item')
    if latest_item is None:
        raise ValueError("找不到任何集數")
        
    enclosure = latest_item.find('enclosure')
    if enclosure is None:
        raise ValueError("找不到音訊檔案")
        
    # 獲取最新一集的標題
    episode_title_element = latest_item.find('title')
    episode_title = episode_title_element.text if episode_title_element is not None else "Latest_Episode"
    
    return enclosure.get('url'), channel_title, episode_title

async def transcribe_podcast(apple_podcast_url):
    try:
        # 初始化 Deepgram
        deepgram = DeepgramClient(DEEPGRAM_API_KEY)
        
        # 從 Apple Podcast URL 獲取音訊檔案
        print('正在獲取 podcast 資訊...')
        itunes_id = get_itunes_id(apple_podcast_url)
        rss_feed_url = get_rss_feed(itunes_id)
        
        # 從 URL 提取 episode_id（如果有的話）
        episode_id = None
        match = re.search(r'i=(\d+)', apple_podcast_url)
        if match:
            episode_id = match.group(1)
        
        # 獲取音訊 URL
        print('正在獲取音訊檔案...')
        audio_url = get_episode_url(rss_feed_url, episode_id)
        print(f"獲取到的音訊URL: {audio_url}")
        
        # 測試URL是否可訪問
        try:
            test_response = requests.head(audio_url, timeout=10)
            print(f"URL狀態碼: {test_response.status_code}")
            print(f"URL內容類型: {test_response.headers.get('Content-Type', '未知')}")
            print(f"URL內容長度: {test_response.headers.get('Content-Length', '未知')}")
            if test_response.status_code != 200:
                print(f"警告：URL可能無法訪問，狀態碼: {test_response.status_code}")
        except Exception as e:
            print(f"測試URL時出錯: {str(e)}")
        
        # 嘗試下載音檔到本地再進行轉錄
        print("正在下載音檔到本地...")
        local_file = "podcast_audio.mp3"
        try:
            # 使用allow_redirects=True確保跟隨重定向
            audio_response = requests.get(audio_url, stream=True, timeout=30, allow_redirects=True)
            print(f"下載狀態碼: {audio_response.status_code}")
            print(f"最終URL: {audio_response.url}")
            
            if audio_response.status_code == 200:
                with open(local_file, 'wb') as f:
                    for chunk in audio_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"音檔已下載到: {local_file}")
                print(f"檔案大小: {os.path.getsize(local_file)} 位元組")
                
                # 檢查檔案是否為空或太小
                if os.path.getsize(local_file) < 1000:  # 小於1KB可能不是有效的音訊檔案
                    print("警告：下載的檔案太小，可能不是有效的音訊檔案")
                    raise ValueError("下載的檔案太小，可能不是有效的音訊檔案")
                
                # 使用本地檔案進行轉錄
                with open(local_file, "rb") as f:
                    buffer_data = f.read()
                
                # 設定轉錄選項
                options = PrerecordedOptions(
                    punctuate=True,  # 添加標點符號
                    diarize=True,    # 識別不同說話者
                    paragraphs=True, # 自動分段
                    language="zh-TW" # 指定語言為繁體中文
                )
                
                print('開始轉錄本地檔案...')
                response = deepgram.listen.rest.v("1").transcribe_file(
                    buffer_data,
                    options=options
                )
            else:
                print(f"下載音檔失敗，狀態碼: {audio_response.status_code}")
                # 如果下載失敗，嘗試使用URL方法
                print('嘗試使用URL方法作為備選...')
                response = deepgram.listen.rest.v("1").transcribe_url(
                    source={"url": audio_url},
                    options=options
                )
        except Exception as e:
            print(f"下載或處理音檔時出錯: {str(e)}")
            # 嘗試使用URL方法作為備選
            print('嘗試使用URL方法作為備選...')
            response = deepgram.listen.rest.v("1").transcribe_url(
                source={"url": audio_url},
                options=options
            )
        
        # 儲存完整的API回應以便調試
        import json
        with open('deepgram_response.json', 'w', encoding='utf-8') as f:
            json.dump(response.to_dict(), f, ensure_ascii=False, indent=2)
        print('完整API回應已儲存到 deepgram_response.json')
        
        # 獲取轉錄文字 - 優先使用段落格式
        try:
            if hasattr(response.results, 'channels') and response.results.channels and \
               hasattr(response.results.channels[0], 'alternatives') and response.results.channels[0].alternatives:
                alt = response.results.channels[0].alternatives[0]
                if hasattr(alt, 'paragraphs') and alt.paragraphs and hasattr(alt.paragraphs, 'transcript'):
                    transcript = alt.paragraphs.transcript
                    print("使用段落格式的轉錄")
                else:
                    transcript = alt.transcript
                    print("使用基本格式的轉錄")
            else:
                raise AttributeError("無法從回應中獲取轉錄")
        except Exception as e:
            print(f"處理轉錄結果時出錯: {str(e)}")
            # 嘗試直接獲取transcript字段
            try:
                transcript = response.results.channels[0].alternatives[0].transcript
                print("使用基本格式的轉錄（備選方法）")
            except:
                transcript = "轉錄失敗，無法獲取結果"
        
        # 儲存到文字檔
        with open('transcript.txt', 'w', encoding='utf-8') as f:
            f.write(transcript)
        
        print('轉錄完成！結果已儲存到 transcript.txt')
    except Exception as e:
        print(f'轉錄過程中發生錯誤：{str(e)}')

async def main():
    # 在這裡輸入從iPhone Podcast分享的URL
    podcast_url = input('請輸入 Apple Podcast URL: ')
    await transcribe_podcast(podcast_url)

if __name__ == '__main__':
    asyncio.run(main())