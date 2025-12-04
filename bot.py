#!/usr/bin/env python3
"""
Telegram Media Archiver Bot

Архивирует медиа-группы (альбомы фото) из Telegram каналов/чатов
с сохранением на локальный диск с описаниями.
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import asyncio

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
BOT_TOKEN = os.getenv('BOT_TOKEN')
DOWNLOAD_DIR = Path(os.getenv('DOWNLOAD_DIR', 'downloads'))
MEDIA_GROUPS_DIR = DOWNLOAD_DIR / 'media_groups'

# Временное хранилище для группировки медиа
media_group_buffer = defaultdict(list)


class MediaArchiver:
    """Класс для архивации медиа из Telegram"""
    
    def __init__(self, download_dir: Path):
        self.download_dir = download_dir
        self.media_groups_dir = download_dir / 'media_groups'
        self.metadata_file = download_dir / 'metadata.json'
        
        # Создание директорий
        self.media_groups_dir.mkdir(parents=True, exist_ok=True)
        
        # Загрузка или создание метаданных
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> dict:
        """Загрузка метаданных из файла"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'groups': [], 'total_files': 0}
    
    def _save_metadata(self):
        """Сохранение метаданных в файл"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
    
    async def save_media_group(self, media_group_id: str, messages: list):
        """Сохранение медиа-группы на диск"""
        try:
            # Создание папки для группы
            group_count = len(self.metadata['groups']) + 1
            group_dir = self.media_groups_dir / f'group_{group_count:04d}'
            group_dir.mkdir(exist_ok=True)
            
            # Информация о группе
            group_info = {
                'media_group_id': media_group_id,
                'date': datetime.now().isoformat(),
                'caption': '',
                'files': [],
                'sender': '',
                'chat_id': None,
                'message_count': len(messages)
            }
            
            # Обработка каждого сообщения в группе
            for idx, msg in enumerate(messages, 1):
                # Получение caption из первого сообщения
                if idx == 1 and msg.caption:
                    group_info['caption'] = msg.caption
                
                # Информация об отправителе
                if msg.from_user:
                    group_info['sender'] = msg.from_user.username or msg.from_user.full_name
                group_info['chat_id'] = msg.chat_id
                
                # Скачивание фото
                if msg.photo:
                    photo = msg.photo[-1]  # Самое большое фото
                    file = await photo.get_file()
                    
                    # Имя файла
                    file_ext = file.file_path.split('.')[-1]
                    filename = f'photo_{idx:02d}.{file_ext}'
                    filepath = group_dir / filename
                    
                    # Скачивание
                    await file.download_to_drive(filepath)
                    
                    group_info['files'].append({
                        'file_id': photo.file_id,
                        'filename': filename,
                        'size': photo.file_size,
                        'width': photo.width,
                        'height': photo.height
                    })
                    
                    logger.info(f"Сохранено: {filepath}")
            
            # Сохранение информации о группе
            info_file = group_dir / 'info.json'
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(group_info, f, ensure_ascii=False, indent=2)
            
            # Обновление общих метаданных
            self.metadata['groups'].append({
                'group_id': media_group_id,
                'folder': group_dir.name,
                'date': group_info['date'],
                'files_count': len(group_info['files']),
                'caption': group_info['caption'][:100] if group_info['caption'] else ''
            })
            self.metadata['total_files'] += len(group_info['files'])
            self._save_metadata()
            
            logger.info(f"✅ Группа {media_group_id} сохранена в {group_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка сохранения группы {media_group_id}: {e}")
            return False


# Инициализация архиватора
archiver = MediaArchiver(DOWNLOAD_DIR)


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик медиа-сообщений"""
    message = update.message
    
    # Проверка на медиа-группу
    if message.media_group_id:
        media_group_id = message.media_group_id
        
        # Добавление сообщения в буфер
        media_group_buffer[media_group_id].append(message)
        
        # Ожидание получения всех сообщений группы (задержка)
        await asyncio.sleep(1)
        
        # Проверка, что это последнее сообщение в группе
        if media_group_buffer[media_group_id]:
            messages = media_group_buffer[media_group_id]
            
            # Сохранение группы
            success = await archiver.save_media_group(media_group_id, messages)
            
            if success:
                # Отправка подтверждения
                await message.reply_text(
                    f"✅ Сохранено {len(messages)} фото из альбома"
                )
            
            # Очистка буфера
            del media_group_buffer[media_group_id]
    
    # Одиночное фото (не в группе)
    elif message.photo:
        photo = message.photo[-1]
        
        # Создание "группы" из одного фото
        single_id = f"single_{message.message_id}"
        success = await archiver.save_media_group(single_id, [message])
        
        if success:
            await message.reply_text("✅ Фото сохранено")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "🤖 *Telegram Media Archiver*\n\n"
        "Отправьте мне фото или альбом фотографий, "
        "и я сохраню их на локальный диск с описаниями.\n\n"
        "📁 Все файлы сохраняются в папку `downloads/media_groups/`\n"
        "📋 Метаданные хранятся в `downloads/metadata.json`",
        parse_mode='Markdown'
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика сохранённых файлов"""
    stats_text = (
        f"📊 *Статистика архивации*\n\n"
        f"📁 Всего групп: {len(archiver.metadata['groups'])}\n"
        f"🖼 Всего файлов: {archiver.metadata['total_files']}\n"
        f"💾 Папка: `{archiver.media_groups_dir}`"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')


def main():
    """Запуск бота"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден в .env файле!")
        return
    
    logger.info("🚀 Запуск Telegram Media Archiver...")
    logger.info(f"📁 Директория загрузок: {DOWNLOAD_DIR.absolute()}")
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики
    application.add_handler(MessageHandler(
        filters.PHOTO, 
        handle_media
    ))
    
    # Команды
    from telegram.ext import CommandHandler
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('stats', stats_command))
    
    # Запуск
    logger.info("✅ Бот запущен и ожидает сообщений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
