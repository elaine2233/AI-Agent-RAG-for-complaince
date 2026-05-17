import os
import logging
from typing import List, Dict, Optional
import config
from src.interfaces import InputProcessor, InputType, UserInput

logger = logging.getLogger(__name__)


class TextInputProcessor(InputProcessor):
    def supported_types(self) -> List[InputType]:
        return [InputType.TEXT]

    def process(self, user_input: UserInput) -> UserInput:
        user_input.text = user_input.text.strip()
        return user_input


class ImageInputProcessor(InputProcessor):
    def supported_types(self) -> List[InputType]:
        return [InputType.IMAGE]

    def process(self, user_input: UserInput) -> UserInput:
        for img in user_input.images:
            if not img.get("description") and img.get("path"):
                img["description"] = self._describe_image(img["path"])
            if not img.get("ocr_text") and img.get("path"):
                img["ocr_text"] = self._ocr_image(img["path"])
        return user_input

    def _describe_image(self, path: str) -> str:
        try:
            import dashscope
            from dashscope import MultiModalConversation
            dashscope.api_key = __import__("config").DASHSCOPE_API_KEY
            if not dashscope.api_key:
                return "[用户上传的图片]"

            messages = [{
                "role": "user",
                "content": [
                    {"image": f"file://{path}"},
                    {"text": "请描述这张图片的内容，特别关注是否有保险营销相关的文字、标语或宣传内容。"},
                ],
            }]
            resp = MultiModalConversation.call(model=config.VL_MODEL, messages=messages)
            if resp.status_code == 200:
                return resp.output.choices[0].message.content
        except Exception as e:
            logger.debug(f"图片描述失败: {e}")
        return "[用户上传的图片]"

    def _ocr_image(self, path: str) -> str:
        try:
            import dashscope
            from dashscope import MultiModalConversation
            dashscope.api_key = __import__("config").DASHSCOPE_API_KEY
            if not dashscope.api_key:
                return ""

            messages = [{
                "role": "user",
                "content": [
                    {"image": f"file://{path}"},
                    {"text": "请提取图片中的所有文字，原样输出。"},
                ],
            }]
            resp = MultiModalConversation.call(model=config.VL_MODEL, messages=messages)
            if resp.status_code == 200:
                return resp.output.choices[0].message.content
        except Exception as e:
            logger.debug(f"图片OCR失败: {e}")
        return ""


class FileInputProcessor(InputProcessor):
    def supported_types(self) -> List[InputType]:
        return [InputType.FILE]

    def process(self, user_input: UserInput) -> UserInput:
        from src.document_parsers import parser_registry

        for f in user_input.files:
            path = f.get("path", "")
            if path and os.path.exists(path):
                try:
                    doc = parser_registry.parse(path)
                    f["extracted_text"] = doc.raw_text
                    f["title"] = doc.title
                    f["format"] = doc.source_format.value
                    if doc.tables:
                        f["tables"] = doc.tables
                    if doc.images:
                        f["images"] = doc.images
                except Exception as e:
                    logger.error(f"文件解析失败 {path}: {e}")
                    f["extracted_text"] = ""
                    f["error"] = str(e)
        return user_input


class MixedInputProcessor(InputProcessor):
    def supported_types(self) -> List[InputType]:
        return [InputType.MIXED]

    def process(self, user_input: UserInput) -> UserInput:
        if user_input.images:
            img_proc = ImageInputProcessor()
            for img in user_input.images:
                temp = UserInput(input_type=InputType.IMAGE, images=[img])
                processed = img_proc.process(temp)
                if processed.images:
                    img.update(processed.images[0])

        if user_input.files:
            file_proc = FileInputProcessor()
            temp = UserInput(input_type=InputType.FILE, files=user_input.files)
            processed = file_proc.process(temp)
            user_input.files = processed.files

        return user_input


class InputProcessorChain:
    def __init__(self):
        self._processors: Dict[InputType, InputProcessor] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(TextInputProcessor())
        self.register(ImageInputProcessor())
        self.register(FileInputProcessor())
        self.register(MixedInputProcessor())

    def register(self, processor: InputProcessor):
        for input_type in processor.supported_types():
            self._processors[input_type] = processor

    def process(self, user_input: UserInput) -> UserInput:
        processor = self._processors.get(user_input.input_type)
        if processor:
            return processor.process(user_input)

        if user_input.input_type == InputType.MIXED:
            return MixedInputProcessor().process(user_input)

        fallback = self._processors.get(InputType.TEXT)
        if fallback:
            return fallback.process(user_input)

        return user_input

    def auto_detect(self, text: str = "", images: List[Dict] = None, files: List[Dict] = None) -> UserInput:
        has_text = bool(text and text.strip())
        has_images = bool(images)
        has_files = bool(files)

        if sum([has_text, has_images, has_files]) > 1:
            input_type = InputType.MIXED
        elif has_images and not has_text and not has_files:
            input_type = InputType.IMAGE
        elif has_files and not has_text and not has_images:
            input_type = InputType.FILE
        else:
            input_type = InputType.TEXT

        return UserInput(
            input_type=input_type,
            text=text or "",
            images=images or [],
            files=files or [],
        )


input_processor_chain = InputProcessorChain()
