from googletrans import Translator

def translate_text(text, target_language='zh'):
    translator = Translator()
    try:
        translated_text = translator.translate(text, dest=target_language).text
        return translated_text
    except Exception as e:
        print(f"Translation error: {e}")
        return text  # 如果翻译失败，返回原文

if __name__ == "__main__":
    text = "Hello, this is a tweet from Twitter."
    translated_text = translate_text(text, target_language='zh')
    print(translated_text)