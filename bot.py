import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from datetime import datetime, time, timedelta
import pytz
import os
import json
import asyncio
from typing import Dict, Any, List

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения Railway
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8409056345:AAEgAOIvZsKO5aezqNoLT8AZbybidygFmhM')

# Таймзона Москвы
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Сообщение для автоответа
AUTO_REPLY_MESSAGE = """Здравствуйте, вы написали в нерабочее время компании!

Мы отвечаем с понедельника по пятницу | c 10:00 до 19:00 по МСК

🤖 **Автоматические команды:**
🏷️ `/price` - Прайс-лист
📋 `/reglament` - Регламент
❓ `/help_client` - Справка по командам

**сообщение автоматическое, отвечать на него не нужно**"""

# ID администраторов
ADMIN_IDS = {7842709072, 1772492746}

# Файлы для сохранения данных
FLAGS_FILE = "auto_reply_flags.json"
WORK_CHAT_FILE = "work_chat.json"
PENDING_MESSAGES_FILE = "pending_messages.json"
FUNNELS_CONFIG_FILE = "funnels_config.json"
EXCLUDED_USERS_FILE = "excluded_users.json"
FUNNELS_STATE_FILE = "funnels_state.json"
MASTER_NOTIFICATION_FILE = "master_notification.json"
CUSTOM_COMMANDS_FILE = "custom_commands.json"

# Глобальная переменная для доступа к приложению
application = None

# ========== КЛАСС ДЛЯ УПРАВЛЕНИЯ КАСТОМНЫМИ КОМАНДАМИ ==========

class CustomCommandsManager:
    def __init__(self):
        self.commands = self.load_commands()
    
    def load_commands(self) -> Dict[str, Any]:
        """Загружает кастомные команды из файла"""
        try:
            if os.path.exists(CUSTOM_COMMANDS_FILE):
                with open(CUSTOM_COMMANDS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки кастомных команд: {e}")
        return {}
    
    def save_commands(self):
        """Сохраняет кастомные команды в файл"""
        try:
            with open(CUSTOM_COMMANDS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.commands, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка сохранения кастомных команд: {e}")
    
    def add_command(self, command_name: str, content_type: str, content: str, description: str = ""):
        """Добавляет новую команду и сразу регистрирует обработчик"""
        self.commands[command_name] = {
            'type': content_type,
            'content': content,
            'description': description,
            'created_at': datetime.now(MOSCOW_TZ).isoformat()
        }
        self.save_commands()
        
        # ДИНАМИЧЕСКАЯ РЕГИСТРАЦИЯ ОБРАБОТЧИКА
        global application
        if application:
            self.register_command_handler(command_name)
            logger.info(f"✅ Динамически зарегистрирован обработчик для: /{command_name}")
    
    def register_command_handler(self, command_name: str):
        """Регистрирует обработчик для конкретной команды"""
        global application
        if application:
            # Удаляем старый обработчик если есть
            for handler in application.handlers[0]:
                if (isinstance(handler, CommandHandler) and 
                    handler.commands and 
                    command_name in handler.commands):
                    application.handlers[0].remove(handler)
                    break
            
            # Добавляем новый обработчик
            application.add_handler(CommandHandler(command_name, handle_custom_command))
    
    def register_all_handlers(self):
        """Регистрирует обработчики для всех команд при запуске"""
        global application
        if application:
            for command_name in self.commands.keys():
                self.register_command_handler(command_name)
            logger.info(f"✅ Зарегистрировано обработчиков для {len(self.commands)} кастомных команд")
    
    def remove_command(self, command_name: str) -> bool:
        """Удаляет команду и её обработчик"""
        if command_name in self.commands:
            # Удаляем связанный файл если есть
            cmd = self.commands[command_name]
            if cmd['type'] in ['photo', 'document', 'video', 'audio']:
                file_path = os.path.join('assets', cmd['content'])
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"✅ Удален файл: {file_path}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка удаления файла {file_path}: {e}")
            
            # УДАЛЯЕМ ОБРАБОТЧИК ИЗ ПРИЛОЖЕНИЯ
            global application
            if application:
                for handler in application.handlers[0]:
                    if (isinstance(handler, CommandHandler) and 
                        handler.commands and 
                        command_name in handler.commands):
                        application.handlers[0].remove(handler)
                        logger.info(f"✅ Удален обработчик для: /{command_name}")
                        break
            
            del self.commands[command_name]
            self.save_commands()
            logger.info(f"✅ Команда удалена: /{command_name}")
            return True
        return False
    
    def get_command(self, command_name: str) -> Dict[str, Any]:
        """Возвращает команду по имени"""
        return self.commands.get(command_name)
    
    def get_all_commands(self) -> Dict[str, Any]:
        """Возвращает все команды"""
        return self.commands

# ========== КЛАСС ДЛЯ УПРАВЛЕНИЯ ГЛАВНЫМ УВЕДОМЛЕНИЕМ ==========

class MasterNotificationManager:
    def __init__(self):
        self.data = self.load_data()
        self.last_notification_time = None
        self.notification_cooldown = 900  # 15 минут в секундах
    
    def load_data(self) -> Dict[str, Any]:
        """Загружает данные главного уведомления из файла"""
        try:
            if os.path.exists(MASTER_NOTIFICATION_FILE):
                with open(MASTER_NOTIFICATION_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки главного уведомления: {e}")
        return {"message_ids": [], "last_update": None}
    
    def save_data(self):
        """Сохраняет данные главного уведомления в файл"""
        try:
            with open(MASTER_NOTIFICATION_FILE, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения главного уведомления: {e}")
    
    def add_message_id(self, message_id: int):
        """Добавляет ID сообщения в список"""
        if "message_ids" not in self.data:
            self.data["message_ids"] = []
        
        self.data["message_ids"].append(message_id)
        self.data["last_update"] = datetime.now(MOSCOW_TZ).isoformat()
        self.save_data()
        logger.info(f"✅ Добавлен ID уведомления: {message_id}")
    
    def get_message_ids(self) -> List[int]:
        """Возвращает список ID сообщений уведомлений"""
        return self.data.get("message_ids", [])
    
    def clear_old_messages(self, keep_last: int = 3):
        """Очищает старые сообщения, оставляя только последние"""
        if "message_ids" in self.data and len(self.data["message_ids"]) > keep_last:
            # Оставляем только последние keep_last сообщений
            self.data["message_ids"] = self.data["message_ids"][-keep_last:]
            self.save_data()
    
    def should_update(self) -> bool:
        """Проверяет, нужно ли обновлять уведомление (каждые 15 минут)"""
        # Если никогда не отправляли - отправляем
        if not self.last_notification_time:
            return True
        
        now = datetime.now(MOSCOW_TZ)
        time_diff = now - self.last_notification_time
        
        return time_diff.total_seconds() >= self.notification_cooldown
    
    def update_notification_time(self):
        """Обновляет время последней отправки уведомления"""
        self.last_notification_time = datetime.now(MOSCOW_TZ)
        logger.info(f"🕐 Обновлено время уведомления: {self.last_notification_time.strftime('%H:%M:%S')}")

# ========== КЛАСС ДЛЯ УПРАВЛЕНИЯ СОСТОЯНИЕМ ВОРОНОК ==========

class FunnelsStateManager:
    def __init__(self):
        self.state = self.load_state()
    
    def load_state(self) -> Dict[str, Any]:
        """Загружает состояние воронок из файла"""
        try:
            if os.path.exists(FUNNELS_STATE_FILE):
                with open(FUNNELS_STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния воронок: {e}")
        
        return {
            "last_funnel_1_check": None,
            "last_funnel_2_check": None, 
            "last_funnel_3_check": None,
            "funnel_1_messages_processed": [],
            "funnel_2_messages_processed": [],
            "funnel_3_messages_processed": []
        }
    
    def save_state(self):
        """Сохраняет состояние воронок в файл"""
        try:
            with open(FUNNELS_STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния воронок: {e}")
    
    def update_last_check(self, funnel_number: int):
        """Обновляет время последней проверки для воронки"""
        self.state[f"last_funnel_{funnel_number}_check"] = datetime.now(MOSCOW_TZ).isoformat()
        self.save_state()
    
    def get_last_check(self, funnel_number: int) -> datetime:
        """Возвращает время последней проверки для воронки"""
        timestamp = self.state.get(f"last_funnel_{funnel_number}_check")
        if timestamp:
            return datetime.fromisoformat(timestamp)
        return datetime.now(MOSCOW_TZ) - timedelta(days=1)
    
    def add_processed_message(self, funnel_number: int, message_key: str):
        """Добавляет сообщение в список обработанных для воронки"""
        key = f"funnel_{funnel_number}_messages_processed"
        if message_key not in self.state[key]:
            self.state[key].append(message_key)
            self.save_state()
    
    def is_message_processed(self, funnel_number: int, message_key: str) -> bool:
        """Проверяет, было ли сообщение уже обработано воронкой"""
        key = f"funnel_{funnel_number}_messages_processed"
        return message_key in self.state[key]
    
    def clear_processed_messages(self, funnel_number: int):
        """Очищает список обработанных сообщений для воронки"""
        key = f"funnel_{funnel_number}_messages_processed"
        self.state[key] = []
        self.save_state()

# ========== КЛАСС ДЛЯ УПРАВЛЕНИЯ ИСКЛЮЧЕНИЯМИ ==========

class ExcludedUsersManager:
    def __init__(self):
        self.excluded_users = self.load_excluded_users()
    
    def load_excluded_users(self) -> Dict[str, Any]:
        """Загружает список исключенных пользователей из файла"""
        try:
            if os.path.exists(EXCLUDED_USERS_FILE):
                with open(EXCLUDED_USERS_FILE, 'r') as f:
                    data = json.load(f)
                    return data
        except Exception as e:
            logger.error(f"Ошибка загрузки исключенных пользователей: {e}")
        
        return {
            "user_ids": [433733509, 1772492746, 1661202178, 478084322, 868325393, 1438860417, 879901619, 6107771545, 253353687, 2113096625, 91047831, 7842709072],
            "usernames": []
        }
    
    def save_excluded_users(self):
        """Сохраняет список исключенных пользователей в файл"""
        try:
            with open(EXCLUDED_USERS_FILE, 'w') as f:
                json.dump(self.excluded_users, f, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения исключенных пользователей: {e}")
    
    def is_user_excluded(self, user_id: int, username: str = None) -> bool:
        """Проверяет, является ли пользователь исключенным"""
        if user_id in self.excluded_users["user_ids"]:
            return True
        
        if username and username.lower() in [u.lower() for u in self.excluded_users["usernames"]]:
            return True
        
        return False
    
    def add_user_id(self, user_id: int) -> bool:
        """Добавляет ID пользователя в исключения"""
        if user_id not in self.excluded_users["user_ids"]:
            self.excluded_users["user_ids"].append(user_id)
            self.save_excluded_users()
            logger.info(f"✅ Добавлен ID в исключения: {user_id}")
            return True
        return False
    
    def add_username(self, username: str) -> bool:
        """Добавляет username в исключения"""
        username = username.lstrip('@').lower()
        if username not in [u.lower() for u in self.excluded_users["usernames"]]:
            self.excluded_users["usernames"].append(username)
            self.save_excluded_users()
            logger.info(f"✅ Добавлен username в исключения: @{username}")
            return True
        return False
    
    def remove_user_id(self, user_id: int) -> bool:
        """Удаляет ID пользователя из исключений"""
        if user_id in self.excluded_users["user_ids"]:
            self.excluded_users["user_ids"].remove(user_id)
            self.save_excluded_users()
            logger.info(f"✅ Удален ID из исключений: {user_id}")
            return True
        return False
    
    def remove_username(self, username: str) -> bool:
        """Удаляет username из исключений"""
        username = username.lstrip('@').lower()
        for u in self.excluded_users["usernames"]:
            if u.lower() == username:
                self.excluded_users["usernames"].remove(u)
                self.save_excluded_users()
                logger.info(f"✅ Удален username из исключений: @{username}")
                return True
        return False
    
    def get_all_excluded(self) -> Dict[str, List]:
        """Возвращает всех исключенных пользователей"""
        return self.excluded_users
    
    def clear_all(self):
        """Очищает все исключения"""
        self.excluded_users = {"user_ids": [], "usernames": []}
        self.save_excluded_users()
        logger.info("✅ Все исключения очищены")

# ========== КЛАССЫ ДЛЯ УПРАВЛЕНИЯ ДАННЫМИ ==========

class FunnelsConfig:
    def __init__(self):
        self.funnels = self.load_funnels()
    
    def load_funnels(self) -> Dict[int, int]:
        """Загружает конфигурацию воронок из файла или использует значения по умолчания"""
        try:
            if os.path.exists(FUNNELS_CONFIG_FILE):
                with open(FUNNELS_CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    return {int(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации воронок: {e}")
        
        return {
            1: 60,    # 1 час
            2: 180,   # 3 часа  
            3: 300    # 5 часов
        }
    
    def save_funnels(self):
        """Сохраняет конфигурацию воронок в файл"""
        try:
            with open(FUNNELS_CONFIG_FILE, 'w') as f:
                json.dump(self.funnels, f, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации воронок: {e}")
    
    def get_funnels(self) -> Dict[int, int]:
        """Возвращает текущую конфигурацию воронок"""
        return self.funnels
    
    def set_funnel_interval(self, funnel_number: int, minutes: int) -> bool:
        """Устанавливает интервал для указанной воронки"""
        if funnel_number in [1, 2, 3] and minutes > 0:
            self.funnels[funnel_number] = minutes
            self.save_funnels()
            logger.info(f"Установлен интервал для воронки {funnel_number}: {minutes} минут")
            return True
        return False
    
    def get_funnel_interval(self, funnel_number: int) -> int:
        """Возвращает интервал для указанной воронки"""
        return self.funnels.get(funnel_number, 0)
    
    def reset_to_default(self):
        """Сбрасывает настройки воронок к значениям по умолчанию"""
        self.funnels = {1: 60, 2: 180, 3: 300}
        self.save_funnels()
        logger.info("Настройки воронок сброшены к значениям по умолчанию")

class AutoReplyFlags:
    def __init__(self):
        self.flags = self.load_flags()
    
    def load_flags(self) -> Dict[str, bool]:
        try:
            if os.path.exists(FLAGS_FILE):
                with open(FLAGS_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки флагов: {e}")
        return {}
    
    def save_flags(self):
        try:
            with open(FLAGS_FILE, 'w') as f:
                json.dump(self.flags, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения флагов: {e}")
    
    def has_replied(self, key: str) -> bool:
        return self.flags.get(key, False)
    
    def set_replied(self, key: str):
        self.flags[key] = True
        self.save_flags()
    
    def clear_replied(self, key: str):
        if key in self.flags:
            del self.flags[key]
            self.save_flags()
    
    def clear_all(self):
        self.flags = {}
        self.save_flags()
    
    def count_flags(self):
        return len(self.flags)

class WorkChatManager:
    def __init__(self):
        self.work_chat_id = self.load_work_chat()
    
    def load_work_chat(self):
        try:
            if os.path.exists(WORK_CHAT_FILE):
                with open(WORK_CHAT_FILE, 'r') as f:
                    data = json.load(f)
                    return data.get('work_chat_id')
        except Exception as e:
            logger.error(f"Ошибка загрузки рабочего чата: {e}")
        return None
    
    def save_work_chat(self, chat_id):
        try:
            with open(WORK_CHAT_FILE, 'w') as f:
                json.dump({'work_chat_id': chat_id}, f)
            self.work_chat_id = chat_id
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения рабочего чата: {e}")
            return False
    
    def get_work_chat_id(self):
        return self.work_chat_id
    
    def is_work_chat_set(self):
        return self.work_chat_id is not None

class PendingMessagesManager:
    def __init__(self, funnels_config: FunnelsConfig):
        self.pending_messages = self.load_pending_messages()
        self.funnels_config = funnels_config
    
    def load_pending_messages(self) -> Dict[str, Any]:
        try:
            if os.path.exists(PENDING_MESSAGES_FILE):
                with open(PENDING_MESSAGES_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки непрочитанных сообщений: {e}")
        return {}
    
    def save_pending_messages(self):
        try:
            with open(PENDING_MESSAGES_FILE, 'w') as f:
                json.dump(self.pending_messages, f, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения непрочитанных сообщений: {e}")
    
    def add_message(self, chat_id: int, user_id: int, message_text: str, message_id: int, chat_title: str = None, username: str = None, first_name: str = None):
        key = f"{chat_id}_{user_id}_{message_id}_{int(datetime.now().timestamp())}"
        
        if not message_text:
            message_text = "[Сообщение без текста]"
        
        self.pending_messages[key] = {
            'chat_id': chat_id,
            'user_id': user_id,
            'message_text': message_text,
            'message_id': message_id,
            'chat_title': chat_title,
            'username': username,
            'first_name': first_name,
            'timestamp': datetime.now(MOSCOW_TZ).isoformat(),
            'funnels_sent': [],
            'current_funnel': 0,
            'message_key': key
        }
        self.save_pending_messages()
        logger.info(f"✅ Добавлено непрочитанное сообщение: {key}")
    
    def remove_message_by_key(self, key: str):
        if key in self.pending_messages:
            del self.pending_messages[key]
            self.save_pending_messages()
            logger.info(f"✅ Удалено непрочитанное сообщение: {key}")
            return True
        return False
    
    def remove_all_chat_messages(self, chat_id: int, user_id: int = None):
        keys_to_remove = []
        for key, message in self.pending_messages.items():
            if message['chat_id'] == chat_id:
                if user_id is None or message['user_id'] == user_id:
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.pending_messages[key]
        
        if keys_to_remove:
            self.save_pending_messages()
            logger.info(f"✅ Удалено {len(keys_to_remove)} сообщений из чата {chat_id}")
            return len(keys_to_remove)
        return 0
    
    def get_all_pending_messages(self) -> List[Dict[str, Any]]:
        return list(self.pending_messages.values())
    
    def mark_funnel_sent(self, message_key: str, funnel_number: int):
        if message_key in self.pending_messages:
            if funnel_number not in self.pending_messages[message_key]['funnels_sent']:
                self.pending_messages[message_key]['funnels_sent'].append(funnel_number)
                self.pending_messages[message_key]['current_funnel'] = funnel_number
                self.save_pending_messages()
    
    def find_messages_by_chat(self, chat_id: int) -> List[Dict[str, Any]]:
        result = []
        for message in self.pending_messages.values():
            if message['chat_id'] == chat_id:
                result.append(message)
        return result
    
    def get_messages_for_funnel(self, funnel_number: int, funnels_state: FunnelsStateManager) -> List[Dict[str, Any]]:
        """Получает сообщения для указанной воронки - ПРОСТАЯ И НАДЕЖНАЯ ЛОГИКА"""
        result = []
        now = datetime.now(MOSCOW_TZ)
        FUNNELS = self.funnels_config.get_funnels()
        funnel_minutes = FUNNELS[funnel_number]
        
        for message_key, message in self.pending_messages.items():
            timestamp = datetime.fromisoformat(message['timestamp'])
            time_diff = now - timestamp
            minutes_passed = int(time_diff.total_seconds() / 60)
            
            funnels_sent = message.get('funnels_sent', [])
            
            # ПРОСТАЯ ЛОГИКА: если прошло достаточно времени и воронка еще не отправлена
            if (minutes_passed >= funnel_minutes and 
                funnel_number not in funnels_sent):
                message['message_key'] = message_key
                message['minutes_passed'] = minutes_passed
                result.append(message)
        
        return result
    
    def update_funnel_statuses(self):
        """Автоматически обновляет статусы воронок - ПРОСТАЯ ЛОГИКА"""
        updated_count = 0
        now = datetime.now(MOSCOW_TZ)
        FUNNELS = self.funnels_config.get_funnels()
        
        for message_key, message in self.pending_messages.items():
            timestamp = datetime.fromisoformat(message['timestamp'])
            time_diff = now - timestamp
            minutes_passed = int(time_diff.total_seconds() / 60)
            
            current_funnel = message.get('current_funnel', 0)
            
            # Определяем текущую воронку на основе времени
            new_funnel = 0
            if minutes_passed >= FUNNELS[3]:
                new_funnel = 3
            elif minutes_passed >= FUNNELS[2]:
                new_funnel = 2
            elif minutes_passed >= FUNNELS[1]:
                new_funnel = 1
            
            # Обновляем если изменилась
            if new_funnel != current_funnel:
                self.pending_messages[message_key]['current_funnel'] = new_funnel
                updated_count += 1
                logger.info(f"🔄 Сообщение {message_key}: воронка {current_funnel} -> {new_funnel} ({minutes_passed} минут)")
        
        if updated_count > 0:
            self.save_pending_messages()
            logger.info(f"✅ Обновлено статусов воронок: {updated_count} сообщений")
        
        return updated_count
    
    def get_all_messages_older_than(self, minutes_threshold: int) -> List[Dict[str, Any]]:
        result = []
        now = datetime.now(MOSCOW_TZ)
        
        for message_key, message in self.pending_messages.items():
            timestamp = datetime.fromisoformat(message['timestamp'])
            time_diff = now - timestamp
            minutes_passed = int(time_diff.total_seconds() / 60)
            
            if minutes_passed >= minutes_threshold:
                message['message_key'] = message_key
                message['minutes_passed'] = minutes_passed
                result.append(message)
        
        return result
    
    def clear_all(self):
        count = len(self.pending_messages)
        self.pending_messages = {}
        self.save_pending_messages()
        logger.info(f"✅ Очищены все непрочитанные сообщения ({count} шт.)")
        return count

# ========== ГЛОБАЛЬНЫЕ ЭКЗЕМПЛЯРЫ ==========

funnels_config = FunnelsConfig()
flags_manager = AutoReplyFlags()
work_chat_manager = WorkChatManager()
pending_messages_manager = PendingMessagesManager(funnels_config)
excluded_users_manager = ExcludedUsersManager()
funnels_state_manager = FunnelsStateManager()
master_notification_manager = MasterNotificationManager()
custom_commands_manager = CustomCommandsManager()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def ensure_assets_folder():
    """Создает папку assets если она не существует"""
    # Используем абсолютный путь
    assets_path = os.path.join(os.getcwd(), 'assets')
    if not os.path.exists(assets_path):
        os.makedirs(assets_path)
        logger.info(f"✅ Папка assets создана: {assets_path}")
    else:
        logger.info(f"✅ Папка assets уже существует: {assets_path}")
    
    # Проверим права на запись
    test_file = os.path.join(assets_path, 'test.txt')
    try:
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        logger.info("✅ Права на запись в assets: OK")
    except Exception as e:
        logger.error(f"❌ Нет прав на запись в assets: {e}")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_manager(user_id: int, username: str = None) -> bool:
    return excluded_users_manager.is_user_excluded(user_id, username)

def is_excluded_user(user_id: int) -> bool:
    return excluded_users_manager.is_user_excluded(user_id)

def is_working_hours():
    now = datetime.now(MOSCOW_TZ)
    current_time = now.time()
    # Проверяем рабочие дни (пн-пт) и время (10:00-19:00)
    is_working_day = now.weekday() < 5  # 0-4 = понедельник-пятница
    is_working_time = current_time >= time(10, 0) and current_time <= time(19, 0)
    
    result = is_working_day and is_working_time
    
    logger.info(f"🕐 Проверка рабочего времени: день недели {now.weekday()}, время {current_time.strftime('%H:%M')}, результат: {'РАБОЧЕЕ' if result else 'НЕРАБОЧЕЕ'}")
    
    return result

def get_chat_display_name(chat_data: Dict[str, Any]) -> str:
    chat_title = chat_data.get('chat_title')
    if chat_title:
        return chat_title
    else:
        return f"Чат {chat_data['chat_id']}"

def get_funnel_emoji(funnel_number: int) -> str:
    emojis = {1: "🟡", 2: "🟠", 3: "🔴"}
    return emojis.get(funnel_number, "⚪")

def format_time_ago(timestamp: str) -> str:
    message_time = datetime.fromisoformat(timestamp)
    now = datetime.now(MOSCOW_TZ)
    time_diff = now - message_time
    
    total_minutes = int(time_diff.total_seconds() / 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    if hours > 0:
        return f"{hours}ч {minutes}м"
    else:
        return f"{minutes}м"

def minutes_to_hours_text(minutes: int) -> str:
    hours = minutes // 60
    if hours == 1:
        return "1 ЧАС"
    elif hours == 3:
        return "3 ЧАСА"
    elif hours == 5:
        return "5 ЧАСОВ"
    else:
        return f"{hours} ЧАСОВ"

# ========== ФУНКЦИИ АВТОМАТИЧЕСКОГО ОБНОВЛЕНИЯ ВОРОНОК ==========

async def update_message_funnel_statuses():
    """Автоматически обновляет статусы воронок для всех сообщений"""
    logger.info("🔄 Автоматическое обновление статусов воронок...")
    return pending_messages_manager.update_funnel_statuses()

# ========== СИСТЕМА ЕДИНОГО УВЕДОМЛЕНИЯ ==========

def create_master_notification_text() -> str:
    """Создает текст единого уведомления со всеми воронками (без дублирования чатов)"""
    FUNNELS = funnels_config.get_funnels()
    
    # Собираем ВСЕ сообщения и группируем по чатам
    all_messages = pending_messages_manager.get_all_pending_messages()
    chats_data = {}
    
    for msg in all_messages:
        chat_id = msg['chat_id']
        if chat_id not in chats_data:
            chats_data[chat_id] = {
                'chat_info': msg,
                'message_count': 0,
                'oldest_time': msg['timestamp'],
                'current_funnel': 0
            }
        chats_data[chat_id]['message_count'] += 1
        if msg['timestamp'] < chats_data[chat_id]['oldest_time']:
            chats_data[chat_id]['oldest_time'] = msg['timestamp']
        
        # Определяем максимальную воронку для чата
        current_funnel = msg.get('current_funnel', 0)
        if current_funnel > chats_data[chat_id]['current_funnel']:
            chats_data[chat_id]['current_funnel'] = current_funnel
    
    # Распределяем чаты по воронкам
    funnel_1_chats = {}
    funnel_2_chats = {}
    funnel_3_chats = {}
    
    for chat_id, chat_data in chats_data.items():
        funnel = chat_data['current_funnel']
        if funnel == 1:
            funnel_1_chats[chat_id] = chat_data
        elif funnel == 2:
            funnel_2_chats[chat_id] = chat_data
        elif funnel == 3:
            funnel_3_chats[chat_id] = chat_data
    
    # Создаем текст уведомления
    notification_text = "📊 **ОБЗОР НЕОТВЕЧЕННЫХ СООБЩЕНИЙ**\n\n"
    
    # Воронка 1
    notification_text += f"🟡 {minutes_to_hours_text(FUNNELS[1])} без ответа\n"
    if funnel_1_chats:
        for chat_id, chat_data in funnel_1_chats.items():
            chat_display = get_chat_display_name(chat_data['chat_info'])
            message_count = chat_data['message_count']
            time_ago = format_time_ago(chat_data['oldest_time'])
            notification_text += f"  • {chat_display} ({message_count} сообщ., {time_ago} назад)\n"
    else:
        notification_text += "  Таких нет\n"
    notification_text += "\n"
    
    # Воронка 2
    notification_text += f"🟠 {minutes_to_hours_text(FUNNELS[2])} без ответа\n"
    if funnel_2_chats:
        for chat_id, chat_data in funnel_2_chats.items():
            chat_display = get_chat_display_name(chat_data['chat_info'])
            message_count = chat_data['message_count']
            time_ago = format_time_ago(chat_data['oldest_time'])
            notification_text += f"  • {chat_display} ({message_count} сообщ., {time_ago} назад)\n"
    else:
        notification_text += "  Таких нет\n"
    notification_text += "\n"
    
    # Воронка 3
    notification_text += f"🔴 БОЛЕЕ {minutes_to_hours_text(FUNNELS[3])} без ответа\n"
    if funnel_3_chats:
        for chat_id, chat_data in funnel_3_chats.items():
            chat_display = get_chat_display_name(chat_data['chat_info'])
            message_count = chat_data['message_count']
            time_ago = format_time_ago(chat_data['oldest_time'])
            notification_text += f"  • {chat_display} ({message_count} сообщ., {time_ago} назад)\n"
    else:
        notification_text += "  Таких нет\n"
    
    # Добавляем общую статистику
    total_messages = len(all_messages)
    total_chats = len(chats_data)
    
    notification_text += f"\n📈 **ИТОГО:** {total_messages} сообщений в {total_chats} чатах"
    notification_text += f"\n⏰ Обновлено: {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}"
    
    return notification_text

async def delete_old_notifications(context: ContextTypes.DEFAULT_TYPE):
    """Удаляет старые уведомления"""
    work_chat_id = work_chat_manager.get_work_chat_id()
    if not work_chat_id:
        return
    
    try:
        message_ids = master_notification_manager.get_message_ids()
        for message_id in message_ids:
            try:
                await context.bot.delete_message(
                    chat_id=work_chat_id,
                    message_id=message_id
                )
                logger.info(f"✅ Удалено старое уведомление: {message_id}")
            except Exception as e:
                logger.warning(f"❌ Не удалось удалить сообщение {message_id}: {e}")
        
        # Очищаем список сообщений после удаления
        master_notification_manager.data["message_ids"] = []
        master_notification_manager.save_data()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении старых уведомлений: {e}")

async def send_new_master_notification(context: ContextTypes.DEFAULT_TYPE, force: bool = False):
    """Отправляет новое уведомление (удаляет старые и отправляет новое)"""
    work_chat_id = work_chat_manager.get_work_chat_id()
    if not work_chat_id:
        logger.error("❌ Не могу отправить уведомление: рабочий чат не установлен")
        return False
    
    # Проверяем cooldown, если не форсированная отправка
    if not force and not master_notification_manager.should_update():
        logger.info("⏳ Cooldown: уведомление не отправляется (еще не прошло 15 минут)")
        return False
    
    try:
        # Сначала удаляем старые уведомления
        await delete_old_notifications(context)
        
        # Затем отправляем новое
        notification_text = create_master_notification_text()
        
        sent_message = await context.bot.send_message(
            chat_id=work_chat_id,
            text=notification_text,
            parse_mode='Markdown'
        )
        
        # Сохраняем ID нового сообщения
        master_notification_manager.add_message_id(sent_message.message_id)
        
        # Обновляем время последней отправки
        master_notification_manager.update_notification_time()
        
        # Очищаем старые сообщения (оставляем только последние 3)
        master_notification_manager.clear_old_messages(keep_last=3)
        
        logger.info("✅ Отправлено новое единое уведомление")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки нового уведомления: {e}")
        return False

async def check_and_send_new_notification(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет и отправляет новое уведомление каждые 15 минут с автоматическим обновлением статусов"""
    logger.info("🔄 Проверка необходимости отправки уведомления...")
    
    # СНАЧАЛА ОБНОВЛЯЕМ СТАТУСЫ ВСЕХ СООБЩЕНИЙ
    updated_count = await update_message_funnel_statuses()
    if updated_count > 0:
        logger.info(f"🔄 Обновлено {updated_count} статусов воронок перед отправкой уведомления")
    
    # ПОТОМ ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ
    await send_new_master_notification(context)

# ========== ОБРАБОТЧИК ОТВЕТОВ МЕНЕДЖЕРА ==========

async def handle_manager_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответы менеджеров и обновляет уведомление"""
    if not update or not update.message:
        return
        
    username = update.message.from_user.username
    if not is_manager(update.message.from_user.id, username):
        return
        
    # ЕСЛИ ЭТО КОМАНДА - НЕ ОБРАБАТЫВАЕМ ЗДЕСЬ, ОНА ОБРАБОТАЕТСЯ CommandHandler
    if update.message.text and update.message.text.startswith('/'):
        logger.info(f"🔍 Команда от менеджера {update.message.from_user.id}, передаем CommandHandler")
        return
    
    # Обрабатываем только обычные сообщения (не команды)
    chat_id = update.message.chat.id
    logger.info(f"🔍 Менеджер ответил в чате {chat_id}")
    
    # Удаляем сообщения из pending для этого чата
    removed_count = pending_messages_manager.remove_all_chat_messages(chat_id)
    
    if removed_count > 0:
        logger.info(f"✅ Удалено {removed_count} сообщений из чата {chat_id} после ответа менеджера")
        
        # Немедленно отправляем новое уведомление (форсированно)
        await send_new_master_notification(context, force=True)

# ========== УНИВЕРСАЛЬНАЯ СИСТЕМА КАСТОМНЫХ КОМАНД ==========

async def create_command_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создать новую команду"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "🆕 **СОЗДАТЬ КОМАНДУ**\n\n"
            "Использование: /create_command <название> <тип> [описание]\n\n"
            "**Типы:**\n"
            "• `text` - текстовая команда\n"
            "• `photo` - команда с фото\n"
            "• `document` - команда с документом\n"
            "• `video` - команда с видео\n"
            "• `audio` - команда с аудио\n\n"
            "**Примеры:**\n"
            "`/create_command price text Наши цены`\n"
            "`/create_command rules document Правила компании`\n"
            "`/create_command contacts text Контактная информация`\n"
            "`/create_command demo video Демонстрация`"
        )
        return
    
    command_name = context.args[0].lower().lstrip('/')
    content_type = context.args[1].lower()
    description = ' '.join(context.args[2:]) if len(context.args) > 2 else ""
    
    # Проверяем валидность типа
    if content_type not in ['text', 'photo', 'document', 'video', 'audio']:
        await update.message.reply_text(
            "❌ Неверный тип команды. Допустимые типы: text, photo, document, video, audio"
        )
        return
    
    # Проверяем, существует ли уже команда
    if command_name in custom_commands_manager.get_all_commands():
        await update.message.reply_text(
            f"❌ Команда `/{command_name}` уже существует!\n"
            f"Используйте /edit_command для изменения."
        )
        return
    
    # Для текстовых команд запрашиваем текст
    if content_type == 'text':
        if not description:
            await update.message.reply_text(
                f"📝 **СОЗДАНИЕ ТЕКСТОВОЙ КОМАНДЫ** `/{command_name}`\n\n"
                f"Отправьте текст, который будет показываться при вызове команды:"
            )
            # Сохраняем временные данные
            context.user_data['creating_command'] = {
                'name': command_name,
                'type': content_type,
                'description': description
            }
        else:
            # Если описание есть, используем его как текст
            custom_commands_manager.add_command(command_name, content_type, description, description)
            await update.message.reply_text(
                f"✅ **Команда создана!**\n\n"
                f"🆕 `/{command_name}` - {description}\n"
                f"📝 Тип: текстовая команда\n\n"
                f"Теперь пользователи могут использовать `/{command_name}`"
            )
    
    # Для фото, документов, видео и аудио ждем файл
    else:
        file_types = {
            'photo': 'изображение',
            'document': 'документ', 
            'video': 'видео',
            'audio': 'аудио'
        }
        
        await update.message.reply_text(
            f"📎 **СОЗДАНИЕ КОМАНДЫ** `/{command_name}`\n\n"
            f"Тип: {content_type}\n"
            f"Описание: {description}\n\n"
            f"📤 **Отправьте файл** ({file_types[content_type]}) "
            f"который будет прикреплен к команде:"
        )
        # Сохраняем временные данные
        context.user_data['creating_command'] = {
            'name': command_name,
            'type': content_type,
            'description': description
        }

async def handle_file_for_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает файл для создания команды"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        return
    
    creating_data = context.user_data.get('creating_command')
    if not creating_data:
        return
    
    command_name = creating_data['name']
    content_type = creating_data['type']
    description = creating_data['description']
    
    try:
        ensure_assets_folder()
        
        # Получаем абсолютный путь к assets
        assets_path = os.path.join(os.getcwd(), 'assets')
        logger.info(f"📁 Работа с папкой: {assets_path}")
        
        file_processed = False
        file_name = ""
        file_path = ""
        
        if content_type == 'photo' and update.message.photo:
            # Обрабатываем фото
            file_extension = '.jpg'
            file_name = f"cmd_{command_name}{file_extension}"
            file_path = os.path.join(assets_path, file_name)
            
            logger.info(f"📸 Скачивание фото в: {file_path}")
            photo_file = await update.message.photo[-1].get_file()
            await photo_file.download_to_drive(file_path)
            file_processed = True
            
        elif content_type == 'document' and update.message.document:
            # Обрабатываем документ
            document = update.message.document
            original_name = document.file_name or 'file.bin'
            file_extension = os.path.splitext(original_name)[1]
            file_name = f"cmd_{command_name}{file_extension}"
            file_path = os.path.join(assets_path, file_name)
            
            logger.info(f"📄 Скачивание документа в: {file_path}")
            file = await document.get_file()
            await file.download_to_drive(file_path)
            file_processed = True
            
        elif content_type == 'video' and update.message.video:
            # Обрабатываем видео
            video = update.message.video
            file_extension = '.mp4'
            file_name = f"cmd_{command_name}{file_extension}"
            file_path = os.path.join(assets_path, file_name)
            
            logger.info(f"🎥 Скачивание видео в: {file_path}")
            file = await video.get_file()
            await file.download_to_drive(file_path)
            file_processed = True
            
        elif content_type == 'audio' and update.message.audio:
            # Обрабатываем аудио
            audio = update.message.audio
            file_extension = '.mp3'
            file_name = f"cmd_{command_name}{file_extension}"
            file_path = os.path.join(assets_path, file_name)
            
            logger.info(f"🎵 Скачивание аудио в: {file_path}")
            file = await audio.get_file()
            await file.download_to_drive(file_path)
            file_processed = True
        
        if file_processed:
            # Проверяем, что файл действительно создан
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                logger.info(f"✅ Файл сохранен: {file_path} ({file_size} байт)")
                
                custom_commands_manager.add_command(command_name, content_type, file_name, description)
                
                type_emojis = {
                    'photo': '📸',
                    'document': '📄', 
                    'video': '🎥',
                    'audio': '🎵'
                }
                
                await update.message.reply_text(
                    f"✅ **Команда создана!**\n\n"
                    f"🆕 `/{command_name}` - {description}\n"
                    f"{type_emojis.get(content_type, '📎')} Тип: команда с {content_type}\n"
                    f"💾 Файл: {file_name}\n"
                    f"📏 Размер: {file_size} байт\n\n"
                    f"Теперь пользователи могут использовать `/{command_name}`"
                )
                
                logger.info(f"✅ Создана команда /{command_name} с файлом {file_name}")
            else:
                await update.message.reply_text("❌ Файл не был сохранен на диск")
                logger.error(f"❌ Файл не создан: {file_path}")
                return
        else:
            await update.message.reply_text(
                "❌ Неверный тип файла. Пожалуйста, отправьте соответствующий файл."
            )
            return
        
        # Очищаем временные данные
        if 'creating_command' in context.user_data:
            del context.user_data['creating_command']
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при создании команды: {str(e)}")
        logger.error(f"❌ Ошибка создания команды: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")

async def handle_text_for_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текст для создания команды"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        return
    
    creating_data = context.user_data.get('creating_command')
    if not creating_data:
        return
    
    command_name = creating_data['name']
    content_type = creating_data['type']
    description = creating_data['description']
    
    if content_type == 'text':
        text_content = update.message.text
        
        custom_commands_manager.add_command(command_name, content_type, text_content, description)
        
        await update.message.reply_text(
            f"✅ **Текстовая команда создана!**\n\n"
            f"🆕 `/{command_name}` - {description}\n"
            f"📝 Тип: текстовая команда\n"
            f"📄 Содержание: {text_content[:100]}{'...' if len(text_content) > 100 else ''}\n\n"
            f"Теперь пользователи могут использовать `/{command_name}`"
        )
        
        logger.info(f"✅ Создана текстовая команда /{command_name}")
        
        # Очищаем временные данные
        if 'creating_command' in context.user_data:
            del context.user_data['creating_command']

async def edit_command_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактировать существующую команду"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args:
        await update.message.reply_text(
            "✏️ **РЕДАКТИРОВАТЬ КОМАНДУ**\n\n"
            "Использование: /edit_command <название>\n\n"
            "Список команд: /list_commands"
        )
        return
    
    command_name = context.args[0].lower().lstrip('/')
    command = custom_commands_manager.get_command(command_name)
    
    if not command:
        await update.message.reply_text(f"❌ Команда `/{command_name}` не найдена")
        return
    
    await update.message.reply_text(
        f"✏️ **РЕДАКТИРОВАНИЕ КОМАНДЫ** `/{command_name}`\n\n"
        f"Тип: {command['type']}\n"
        f"Описание: {command['description']}\n\n"
        f"Что вы хотите сделать?\n"
        f"• Отправьте новый текст (для текстовых команд)\n"
        f"• Отправьте новый файл (для фото/документов/видео/аудио)\n"
        f"• Используйте /delete_command для удаления"
    )
    
    context.user_data['editing_command'] = command_name

async def delete_command_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить команду"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🗑️ **УДАЛИТЬ КОМАНДУ**\n\n"
            "Использование: /delete_command <название>\n\n"
            "Список команд: /list_commands"
        )
        return
    
    command_name = context.args[0].lower().lstrip('/')
    
    if custom_commands_manager.remove_command(command_name):
        await update.message.reply_text(f"✅ Команда `/{command_name}` удалена")
    else:
        await update.message.reply_text(f"❌ Команда `/{command_name}` не найдена")

async def list_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все кастомные команды"""
    if not update or not update.message:
        return
        
    commands = custom_commands_manager.get_all_commands()
    
    if not commands:
        await update.message.reply_text(
            "📝 **КАСТОМНЫЕ КОМАНДЫ**\n\n"
            "Пока нет созданных команд.\n"
            "Используйте /create_command чтобы создать первую команду!"
        )
        return
    
    text = "📝 **ВСЕ КАСТОМНЫЕ КОМАНДЫ**\n\n"
    
    for i, (cmd_name, cmd_data) in enumerate(commands.items(), 1):
        type_emoji = {
            'text': '📝',
            'photo': '📸', 
            'document': '📄',
            'video': '🎥',
            'audio': '🎵'
        }.get(cmd_data['type'], '📎')
        
        text += f"{i}. `/{cmd_name}` {type_emoji}\n"
        text += f"   📋 {cmd_data['description']}\n"
        text += f"   ⚙️ Тип: {cmd_data['type']}\n\n"
    
    text += f"📊 Всего команд: {len(commands)}\n"
    text += "⚙️ Управление: /create_command, /edit_command, /delete_command"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def handle_custom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ВСЕ кастомные команды"""
    if not update or not update.message:
        logger.error("❌ handle_custom_command: нет update или message")
        return
    
    # Получаем название команды (без /)
    command_text = update.message.text
    command_name = command_text.lstrip('/').split(' ')[0].lower()
    
    logger.info(f"🔍 Обработка кастомной команды: '{command_text}' -> извлечено имя: '{command_name}'")
    
    # Отладочная информация
    all_commands = list(custom_commands_manager.get_all_commands().keys())
    logger.info(f"📋 Все доступные команды: {all_commands}")
    
    # Ищем команду в кастомных командах
    command = custom_commands_manager.get_command(command_name)
    if not command:
        logger.error(f"❌ Команда '{command_name}' не найдена в базе")
        logger.info(f"📋 Доступные команды: {all_commands}")
        return
    
    logger.info(f"🔄 Выполнение кастомной команды: /{command_name} (тип: {command['type']})")
    
    try:
        if command['type'] == 'text':
            await update.message.reply_text(
                command['content'],
                parse_mode='Markdown'
            )
        
        elif command['type'] == 'photo':
            file_path = os.path.join('assets', command['content'])
            logger.info(f"📁 Поиск файла: {file_path}")
            if os.path.exists(file_path):
                logger.info(f"✅ Файл найден, отправка...")
                with open(file_path, 'rb') as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=command.get('description', ''),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Файл не найден")
                logger.error(f"❌ Файл не найден: {file_path}")
        
        elif command['type'] == 'document':
            file_path = os.path.join('assets', command['content'])
            logger.info(f"📁 Поиск файла: {file_path}")
            if os.path.exists(file_path):
                logger.info(f"✅ Файл найден, отправка...")
                with open(file_path, 'rb') as document:
                    await update.message.reply_document(
                        document=document,
                        filename=command['content'],
                        caption=command.get('description', ''),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Файл не найден")
        
        elif command['type'] == 'video':
            file_path = os.path.join('assets', command['content'])
            logger.info(f"📁 Поиск файла: {file_path}")
            if os.path.exists(file_path):
                logger.info(f"✅ Файл найден, отправка...")
                with open(file_path, 'rb') as video:
                    await update.message.reply_video(
                        video=video,
                        caption=command.get('description', ''),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Файл не найден")
        
        elif command['type'] == 'audio':
            file_path = os.path.join('assets', command['content'])
            logger.info(f"📁 Поиск файла: {file_path}")
            if os.path.exists(file_path):
                logger.info(f"✅ Файл найден, отправка...")
                with open(file_path, 'rb') as audio:
                    await update.message.reply_audio(
                        audio=audio,
                        caption=command.get('description', ''),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Файл не найден")
        
        logger.info(f"✅ Кастомная команда выполнена: /{command_name}")
        
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при выполнении команды")
        logger.error(f"❌ Ошибка выполнения команды /{command_name}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")

async def check_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить файлы в assets"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    assets_path = os.path.join(os.getcwd(), 'assets')
    
    if not os.path.exists(assets_path):
        await update.message.reply_text("❌ Папка assets не существует!")
        return
    
    files = os.listdir(assets_path)
    
    if not files:
        await update.message.reply_text("📁 Папка assets пуста")
        return
    
    text = "📁 **ФАЙЛЫ В ASSETS:**\n\n"
    for i, file in enumerate(files, 1):
        file_path = os.path.join(assets_path, file)
        file_size = os.path.getsize(file_path)
        text += f"{i}. `{file}` - {file_size} байт\n"
    
    text += f"\n📊 Всего файлов: {len(files)}"
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ========== КОМАНДЫ БОТА ==========

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message:
        return
        
    await update.message.reply_text(
        "🤖 Бот-автоответчик запущен!\n\n"
        "📋 Доступные команды:\n"
        "/status - статус системы\n"
        "/funnels - настройки воронок\n"
        "/pending - список непрочитанных\n"
        "/managers - список менеджеров\n"
        "/stats - статистика\n"
        "/help - помощь\n\n"
        "🆕 **Управление командами:**\n"
        "/create_command - создать команду\n"
        "/edit_command - редактировать команду\n"
        "/delete_command - удалить команду\n"
        "/list_commands - список команд\n"
        "/check_files - проверить файлы\n\n"
        "👥 **Управление исключениями:**\n"
        "/add_exception - добавить исключение\n"
        "/remove_exception - удалить исключение\n"
        "/list_exceptions - список исключений\n"
        "/clear_exceptions - очистить все исключения"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message:
        return
        
    help_text = """
📖 **СПРАВКА ПО КОМАНДАМ БОТА**

**Основные команды:**
/start - запуск бота
/status - статус системы
/help - эта справка

**Управление воронками:**
/funnels - текущие настройки воронок
/set_funnel_1 <минуты> - установить интервал 1-й воронки
/set_funnel_2 <минуты> - установить интервал 2-й воронки  
/set_funnel_3 <минуты> - установить интервал 3-й воронки
/reset_funnels - сбросить настройки воронок
/force_update_funnels - принудительно обновить статусы воронок

**🆕 Управление кастомными командами:**
/create_command - создать новую команду
/edit_command - редактировать команду
/delete_command - удалить команду  
/list_commands - список всех команд
/check_files - проверить файлы в assets

**Рабочий чат:**
/set_work_chat - установить этот чат как рабочий (для уведомлений)

**Управление сообщениями:**
/pending - список непрочитанных сообщений
/clear_chat - очистить сообщения из текущего чата
/clear_all - очистить все сообщения

**Управление исключениями:**
/add_exception <ID/@username> - добавить менеджера
/remove_exception <ID/@username> - удалить менеджера
/list_exceptions - список всех менеджеров
/clear_exceptions - очистить все исключения

**Обновление уведомления:**
/update_notification - обновить единое уведомление

**Статистика:**
/stats - статистика системы
/managers - список менеджеров

📝 **Логика работы воронок:**
🟡 Воронка 1: через 1 час без ответа
🟠 Воронка 2: через 3 часа без ответа
🔴 Воронка 3: через 5 часов без ответа
**БЕЗ ДУБЛИРОВАНИЯ** - каждый чат показывается только в одной воронке

🆕 **Кастомные команды:**
Создавайте любые команды с текстом, фото, документами, видео и аудио!
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    FUNNELS = funnels_config.get_funnels()
    now = datetime.now(MOSCOW_TZ)
    excluded_users = excluded_users_manager.get_all_excluded()
    total_excluded = len(excluded_users["user_ids"]) + len(excluded_users["usernames"])
    
    # Получаем статистику по воронкам (без дублирования)
    all_messages = pending_messages_manager.get_all_pending_messages()
    chats_data = {}
    
    for msg in all_messages:
        chat_id = msg['chat_id']
        if chat_id not in chats_data:
            chats_data[chat_id] = {'current_funnel': 0}
        
        current_funnel = msg.get('current_funnel', 0)
        if current_funnel > chats_data[chat_id]['current_funnel']:
            chats_data[chat_id]['current_funnel'] = current_funnel
    
    funnel_1_count = sum(1 for chat_data in chats_data.values() if chat_data['current_funnel'] == 1)
    funnel_2_count = sum(1 for chat_data in chats_data.values() if chat_data['current_funnel'] == 2)
    funnel_3_count = sum(1 for chat_data in chats_data.values() if chat_data['current_funnel'] == 3)
    
    # Время последнего уведомления
    last_notification = master_notification_manager.last_notification_time
    last_notification_str = last_notification.strftime('%H:%M:%S') if last_notification else "Никогда"
    
    # Статистика кастомных команд
    custom_commands = custom_commands_manager.get_all_commands()
    command_stats = {}
    for cmd in custom_commands.values():
        cmd_type = cmd['type']
        command_stats[cmd_type] = command_stats.get(cmd_type, 0) + 1
    
    # Проверяем папку assets
    assets_path = os.path.join(os.getcwd(), 'assets')
    assets_exists = os.path.exists(assets_path)
    assets_files = len(os.listdir(assets_path)) if assets_exists else 0
    
    status_text = f"""
📊 **СТАТУС СИСТЕМЫ**

⏰ **Время:** {now.strftime('%d.%m.%Y %H:%M:%S')}
🕐 **Рабочие часы:** {'✅ ДА' if is_working_hours() else '❌ НЕТ'}

📋 **Непрочитанные сообщения:** {len(all_messages)}
🚩 **Флаги автоответов:** {flags_manager.count_flags()}
💬 **Рабочий чат:** {'✅ Установлен' if work_chat_manager.is_work_chat_set() else '❌ Не установлен'}
📢 **Последнее уведомление:** {last_notification_str}

🆕 **КАСТОМНЫЕ КОМАНДЫ:** {len(custom_commands)}
📝 Текст: {command_stats.get('text', 0)}
📸 Фото: {command_stats.get('photo', 0)}
📄 Документы: {command_stats.get('document', 0)}
🎥 Видео: {command_stats.get('video', 0)}
🎵 Аудио: {command_stats.get('audio', 0)}
📁 **Папка assets:** {'✅ Существует' if assets_exists else '❌ Не существует'}
📄 **Файлов в assets:** {assets_files}

⚙️ **НАСТРОЙКИ ВОРОНОК:**
🟡 Воронка 1: {FUNNELS[1]} мин ({minutes_to_hours_text(FUNNELS[1])}) - {funnel_1_count} чатов
🟠 Воронка 2: {FUNNELS[2]} мин ({minutes_to_hours_text(FUNNELS[2])}) - {funnel_2_count} чатов
🔴 Воронка 3: {FUNNELS[3]} мин ({minutes_to_hours_text(FUNNELS[3])}) - {funnel_3_count} чатов

👥 **Менеджеров в системе:** {total_excluded} ({len(excluded_users["user_ids"])} ID + {len(excluded_users["usernames"])} username)

🔄 **Логика уведомлений:** Удаление старого + отправка нового каждые 15 минут
⏳ **Cooldown:** {'✅ Активен' if not master_notification_manager.should_update() else '❌ Можно отправлять'}
🔧 **Логика воронок:** ✅ Без дублирования (1 чат = 1 воронка)
    """
    
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def funnels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие настройки воронок"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    FUNNELS = funnels_config.get_funnels()
    
    text = "⚙️ **НАСТРОЙКИ ВОРОНОК УВЕДОМЛЕНИЙ**\n\n"
    text += f"🟡 Воронка 1: {FUNNELS[1]} минут ({minutes_to_hours_text(FUNNELS[1])})\n"
    text += f"🟠 Воронка 2: {FUNNELS[2]} минут ({minutes_to_hours_text(FUNNELS[2])})\n"
    text += f"🔴 Воронка 3: {FUNNELS[3]} минут ({minutes_to_hours_text(FUNNELS[3])})\n\n"
    text += "💡 **Команды для изменения:**\n"
    text += "/set_funnel_1 <минуты> - установить 1-ю воронку\n"
    text += "/set_funnel_2 <минуты> - установить 2-ю воронку\n"
    text += "/set_funnel_3 <минуты> - установить 3-ю воронку\n"
    text += "/reset_funnels - сбросить настройки по умолчанию"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def set_funnel_1_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить интервал для воронки 1"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите интервал в минутах: /set_funnel_1 <минуты>")
        return
    
    try:
        minutes = int(context.args[0])
        if minutes <= 0:
            await update.message.reply_text("❌ Интервал должен быть положительным числом")
            return
        
        if funnels_config.set_funnel_interval(1, minutes):
            await update.message.reply_text(f"✅ Воронка 1 установлена на {minutes} минут ({minutes_to_hours_text(minutes)})")
        else:
            await update.message.reply_text("❌ Ошибка при установке воронки")
    except ValueError:
        await update.message.reply_text("❌ Укажите корректное число минут")

async def set_funnel_2_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить интервал для воронки 2"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите интервал в минутах: /set_funnel_2 <минуты>")
        return
    
    try:
        minutes = int(context.args[0])
        if minutes <= 0:
            await update.message.reply_text("❌ Интервал должен быть положительным числом")
            return
        
        if funnels_config.set_funnel_interval(2, minutes):
            await update.message.reply_text(f"✅ Воронка 2 установлена на {minutes} минут ({minutes_to_hours_text(minutes)})")
        else:
            await update.message.reply_text("❌ Ошибка при установке воронки")
    except ValueError:
        await update.message.reply_text("❌ Укажите корректное число минут")

async def set_funnel_3_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить интервал для воронки 3"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите интервал в минутах: /set_funnel_3 <минуты>")
        return
    
    try:
        minutes = int(context.args[0])
        if minutes <= 0:
            await update.message.reply_text("❌ Интервал должен быть положительным числом")
            return
        
        if funnels_config.set_funnel_interval(3, minutes):
            await update.message.reply_text(f"✅ Воронка 3 установлена на {minutes} минут ({minutes_to_hours_text(minutes)})")
        else:
            await update.message.reply_text("❌ Ошибка при установке воронки")
    except ValueError:
        await update.message.reply_text("❌ Укажите корректное число минут")

async def reset_funnels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбросить настройки воронок к значениям по умолчанию"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    funnels_config.reset_to_default()
    await update.message.reply_text("✅ Настройки воронок сброшены к значениям по умолчанию")

async def force_update_funnels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно обновить статусы воронок"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    updated_count = await update_message_funnel_statuses()
    await update.message.reply_text(f"✅ Принудительно обновлены статусы воронок для {updated_count} сообщений")

async def set_work_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить текущий чат как рабочий для уведомлений"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    chat_id = update.message.chat.id
    chat_title = update.message.chat.title or "Личные сообщения"
    
    if work_chat_manager.save_work_chat(chat_id):
        await update.message.reply_text(
            f"✅ **Этот чат установлен как рабочий для уведомлений!**\n\n"
            f"📝 Название: {chat_title}\n"
            f"🆔 ID: {chat_id}\n\n"
            f"Теперь все уведомления о непрочитанных сообщениях будут приходить сюда."
        )
        logger.info(f"✅ Рабочий чат установлен: {chat_title} (ID: {chat_id})")
        
        # Немедленно отправляем тестовое уведомление
        await send_new_master_notification(context, force=True)
    else:
        await update.message.reply_text("❌ Ошибка при установке рабочего чата")

async def managers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список менеджеров"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    excluded_users = excluded_users_manager.get_all_excluded()
    
    text = "👥 **СПИСОК МЕНЕДЖЕРОВ**\n\n"
    
    text += "🔹 **По ID пользователей:**\n"
    if excluded_users["user_ids"]:
        for user_id in excluded_users["user_ids"]:
            text += f"  • {user_id}\n"
    else:
        text += "  Нет пользователей по ID\n"
    
    text += "\n🔹 **По username:**\n"
    if excluded_users["usernames"]:
        for username in excluded_users["usernames"]:
            text += f"  • @{username}\n"
    else:
        text += "  Нет пользователей по username\n"
    
    text += f"\n📊 Всего менеджеров: {len(excluded_users['user_ids']) + len(excluded_users['usernames'])}"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    all_messages = pending_messages_manager.get_all_pending_messages()
    flags_count = flags_manager.count_flags()
    excluded_users = excluded_users_manager.get_all_excluded()
    total_excluded = len(excluded_users["user_ids"]) + len(excluded_users["usernames"])
    
    # Группируем сообщения по чатам
    chats_data = {}
    for msg in all_messages:
        chat_id = msg['chat_id']
        if chat_id not in chats_data:
            chats_data[chat_id] = {
                'count': 0,
                'title': msg.get('chat_title', f'Чат {chat_id}'),
                'oldest': msg['timestamp']
            }
        chats_data[chat_id]['count'] += 1
        if msg['timestamp'] < chats_data[chat_id]['oldest']:
            chats_data[chat_id]['oldest'] = msg['timestamp']
    
    text = "📊 **СТАТИСТИКА СИСТЕМЫ**\n\n"
    text += f"📨 **Непрочитанные сообщения:** {len(all_messages)}\n"
    text += f"💬 **Активные чаты:** {len(chats_data)}\n"
    text += f"🚩 **Флаги автоответов:** {flags_count}\n"
    text += f"👥 **Менеджеров в системе:** {total_excluded}\n"
    text += f"🆕 **Кастомных команд:** {len(custom_commands_manager.get_all_commands())}\n\n"
    
    text += "📋 **Сообщения по чатам:**\n"
    if chats_data:
        for chat_id, data in list(chats_data.items())[:10]:  # Показываем первые 10 чатов
            time_ago = format_time_ago(data['oldest'])
            text += f"  • {data['title']}: {data['count']} сообщ. ({time_ago} назад)\n"
        if len(chats_data) > 10:
            text += f"  ... и еще {len(chats_data) - 10} чатов\n"
    else:
        text += "  Нет непрочитанных сообщений\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список непрочитанных сообщений"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    all_messages = pending_messages_manager.get_all_pending_messages()
    
    if not all_messages:
        await update.message.reply_text("✅ Нет непрочитанных сообщений")
        return
    
    text = "📋 **НЕПРОЧИТАННЫЕ СООБЩЕНИЯ**\n\n"
    
    # Группируем по чатам
    chats_data = {}
    for msg in all_messages:
        chat_id = msg['chat_id']
        if chat_id not in chats_data:
            chats_data[chat_id] = {
                'messages': [],
                'title': msg.get('chat_title', f'Чат {chat_id}'),
                'oldest': msg['timestamp']
            }
        chats_data[chat_id]['messages'].append(msg)
        if msg['timestamp'] < chats_data[chat_id]['oldest']:
            chats_data[chat_id]['oldest'] = msg['timestamp']
    
    for chat_id, data in chats_data.items():
        time_ago = format_time_ago(data['oldest'])
        funnel = max(msg.get('current_funnel', 0) for msg in data['messages'])
        funnel_emoji = get_funnel_emoji(funnel)
        
        text += f"{funnel_emoji} **{data['title']}**\n"
        text += f"   📨 Сообщений: {len(data['messages'])}\n"
        text += f"   ⏰ Самое старое: {time_ago} назад\n"
        text += f"   🚪 Воронка: {funnel}\n\n"
    
    text += f"📊 Всего: {len(all_messages)} сообщений в {len(chats_data)} чатах"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def clear_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить сообщения из текущего чата"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    chat_id = update.message.chat.id
    removed_count = pending_messages_manager.remove_all_chat_messages(chat_id)
    
    if removed_count > 0:
        await update.message.reply_text(f"✅ Удалено {removed_count} сообщений из этого чата")
        # Обновляем уведомление
        await send_new_master_notification(context, force=True)
    else:
        await update.message.reply_text("✅ В этом чате нет непрочитанных сообщений")

async def clear_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить все непрочитанные сообщения"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    removed_count = pending_messages_manager.clear_all()
    
    if removed_count > 0:
        await update.message.reply_text(f"✅ Удалены все непрочитанные сообщения ({removed_count} шт.)")
        # Обновляем уведомление
        await send_new_master_notification(context, force=True)
    else:
        await update.message.reply_text("✅ Нет непрочитанных сообщений для очистки")

async def add_exception_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить менеджера в исключения"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args:
        await update.message.reply_text(
            "👥 **ДОБАВИТЬ МЕНЕДЖЕРА**\n\n"
            "Использование: /add_exception <ID_пользователя или @username>\n\n"
            "Примеры:\n"
            "/add_exception 123456789\n"
            "/add_exception @username"
        )
        return
    
    identifier = context.args[0]
    
    # Пробуем как ID
    if identifier.isdigit():
        user_id = int(identifier)
        if excluded_users_manager.add_user_id(user_id):
            await update.message.reply_text(f"✅ Пользователь с ID {user_id} добавлен в менеджеры")
        else:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} уже является менеджером")
    # Или как username
    elif identifier.startswith('@'):
        username = identifier.lstrip('@')
        if excluded_users_manager.add_username(username):
            await update.message.reply_text(f"✅ Пользователь @{username} добавлен в менеджеры")
        else:
            await update.message.reply_text(f"❌ Пользователь @{username} уже является менеджером")
    else:
        await update.message.reply_text("❌ Укажите ID пользователя или @username")

async def remove_exception_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить менеджера из исключений"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    if not context.args:
        await update.message.reply_text(
            "👥 **УДАЛИТЬ МЕНЕДЖЕРА**\n\n"
            "Использование: /remove_exception <ID_пользователя или @username>\n\n"
            "Примеры:\n"
            "/remove_exception 123456789\n"
            "/remove_exception @username"
        )
        return
    
    identifier = context.args[0]
    
    # Пробуем как ID
    if identifier.isdigit():
        user_id = int(identifier)
        if excluded_users_manager.remove_user_id(user_id):
            await update.message.reply_text(f"✅ Пользователь с ID {user_id} удален из менеджеров")
        else:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден в менеджерах")
    # Или как username
    elif identifier.startswith('@'):
        username = identifier.lstrip('@')
        if excluded_users_manager.remove_username(username):
            await update.message.reply_text(f"✅ Пользователь @{username} удален из менеджеров")
        else:
            await update.message.reply_text(f"❌ Пользователь @{username} не найден в менеджерах")
    else:
        await update.message.reply_text("❌ Укажите ID пользователя или @username")

async def list_exceptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список всех менеджеров"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    await managers_command(update, context)  # Используем существующую функцию

async def clear_exceptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить все исключения"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    excluded_users_manager.clear_all()
    await update.message.reply_text("✅ Все менеджеры удалены из исключений")

async def update_notification_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновить единое уведомление"""
    if not update or not update.message:
        return
        
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды")
        return
    
    await update.message.reply_text("🔄 Обновление уведомления...")
    await send_new_master_notification(context, force=True)

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщения в группах"""
    if not update or not update.message:
        return
        
    chat_title = update.message.chat.title or "Без названия"
    logger.info(f"📨 Получено групповое сообщение: {chat_title} - {update.message.text[:50] if update.message.text else '[без текста]'}...")
    
    # Игнорируем сообщения от самого бота
    if update.message.from_user.id == context.bot.id:
        return
        
    # Игнорируем менеджеров (но команды менеджеров будут обработаны CommandHandler)
    username = update.message.from_user.username
    if is_manager(update.message.from_user.id, username):
        # Если это команда - пропускаем для CommandHandler
        if update.message.text and update.message.text.startswith('/'):
            logger.info(f"🔍 Команда от менеджера {update.message.from_user.id}, передаем CommandHandler")
            return
        # Если обычное сообщение - обрабатываем как ответ менеджера
        else:
            logger.info(f"🔍 Обычное сообщение от менеджера {update.message.from_user.id}, обрабатываем")
            await handle_manager_reply(update, context)
            return
        
    # Игнорируем служебные сообщения
    if (update.message.new_chat_members or 
        update.message.left_chat_member or 
        update.message.pinned_message or
        update.edited_message):
        logger.info("🔍 Служебное сообщение, пропускаем")
        return
        
    # Игнорируем команды (они обрабатываются отдельно CommandHandler)
    if update.message.text and update.message.text.startswith('/'):
        logger.info(f"🔍 Команда {update.message.text}, пропускаем для CommandHandler")
        return
        
    # Игнорируем пустые сообщения
    if update.message.text and len(update.message.text.strip()) < 1:
        logger.info("🔍 Пустое сообщение, пропускаем")
        return

    logger.info(f"🔍 Обычное сообщение от клиента, обрабатываем...")
    
    # Обрабатываем обычные сообщения от клиентов
    chat_id = update.message.chat.id
    if not is_working_hours():
        # Нерабочее время - отправляем автоответ
        replied_key = f'chat_{chat_id}'
        if not flags_manager.has_replied(replied_key):
            logger.info(f"🕐 Нерабочее время, отправляем автоответ в чат {chat_id}")
            await update.message.reply_text(AUTO_REPLY_MESSAGE)
            flags_manager.set_replied(replied_key)
            logger.info(f"✅ Автоответ отправлен в чат {chat_id} (нерабочее время)")
        else:
            logger.info(f"🕐 Автоответ уже был отправлен в этот чат ранее")
    else:
        # Рабочее время - добавляем в непрочитанные
        replied_key = f'chat_{chat_id}'
        if flags_manager.has_replied(replied_key):
            flags_manager.clear_replied(replied_key)
        
        username = update.message.from_user.username
        first_name = update.message.from_user.first_name
        message_text = update.message.text or update.message.caption or "[Сообщение без текста]"
        
        logger.info(f"🕐 Рабочее время, добавляем в непрочитанные: {message_text[:50]}...")
        
        pending_messages_manager.add_message(
            chat_id=update.message.chat.id,
            user_id=update.message.from_user.id,
            message_text=message_text,
            message_id=update.message.message_id,
            chat_title=chat_title,
            username=username,
            first_name=first_name
        )
        logger.info(f"✅ Добавлено в непрочитанные: чат '{chat_title}', пользователь {first_name or username or update.message.from_user.id}")
        
        # Немедленно обновляем уведомление
        await send_new_master_notification(context, force=True)

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает личные сообщения"""
    if not update or not update.message:
        return
        
    logger.info(f"📨 Получено личное сообщение от {update.message.from_user.id}: {update.message.text[:50] if update.message.text else '[без текста]'}...")
    
    # Игнорируем сообщения от самого бота
    if update.message.from_user.id == context.bot.id:
        return
        
    # Игнорируем менеджеров
    username = update.message.from_user.username
    if is_manager(update.message.from_user.id, username):
        logger.info(f"🔍 Сообщение от менеджера {update.message.from_user.id}, пропускаем")
        await handle_manager_reply(update, context)
        return
        
    # Игнорируем служебные сообщения
    if (update.message.new_chat_members or 
        update.message.left_chat_member or 
        update.message.pinned_message or
        update.edited_message):
        logger.info("🔍 Служебное сообщение, пропускаем")
        return
        
    # Игнорируем команды (они обрабатываются отдельно CommandHandler)
    if update.message.text and update.message.text.startswith('/'):
        logger.info(f"🔍 Команда {update.message.text}, пропускаем для CommandHandler")
        return
        
    # Игнорируем пустые сообщения
    if update.message.text and len(update.message.text.strip()) < 1:
        logger.info("🔍 Пустое сообщение, пропускаем")
        return

    logger.info(f"🔍 Обычное сообщение от клиента, обрабатываем...")
    
    # Обрабатываем обычные сообщения от клиентов
    user_id = update.message.from_user.id
    if not is_working_hours():
        # Нерабочее время - отправляем автоответ
        replied_key = f'user_{user_id}'
        if not flags_manager.has_replied(replied_key):
            logger.info(f"🕐 Нерабочее время, отправляем автоответ пользователю {user_id}")
            await update.message.reply_text(AUTO_REPLY_MESSAGE)
            flags_manager.set_replied(replied_key)
            logger.info(f"✅ Автоответ отправлен пользователю {user_id} (нерабочее время)")
        else:
            logger.info(f"🕐 Автоответ уже был отправлен этому пользователю ранее")
    else:
        # Рабочее время - добавляем в непрочитанные
        replied_key = f'user_{user_id}'
        if flags_manager.has_replied(replied_key):
            flags_manager.clear_replied(replied_key)
        
        username = update.message.from_user.username
        first_name = update.message.from_user.first_name
        message_text = update.message.text or update.message.caption or "[Сообщение без текста]"
        
        logger.info(f"🕐 Рабочее время, добавляем в непрочитанные: {message_text[:50]}...")
        
        pending_messages_manager.add_message(
            chat_id=update.message.chat.id,
            user_id=update.message.from_user.id,
            message_text=message_text,
            message_id=update.message.message_id,
            username=username,
            first_name=first_name
        )
        logger.info(f"✅ Добавлено в непрочитанные: пользователь {first_name or username or user_id}")
        
        # Немедленно обновляем уведомление
        await send_new_master_notification(context, force=True)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок - логирует в консоль, но не отправляет уведомления в Telegram"""
    logger.error(f"💥 Ошибка при обработке сообщения: {context.error}")
    
    if update:
        logger.error(f"💥 Update object: {update}")
        if update.message:
            logger.error(f"💥 Message info: chat_id={update.message.chat.id}, user_id={update.message.from_user.id if update.message.from_user else 'None'}")
    
    # Логируем дополнительную информацию об ошибке
    logger.error(f"💥 Traceback: {context.error.__traceback__}")

# ========== ЗАПУСК БОТА ==========

def main():
    global application  # Делаем application глобальной
    
    try:
        # Временная диагностика
        print("=" * 50)
        print("🔍 ДИАГНОСТИКА ФАЙЛОВОЙ СИСТЕМЫ")
        print("=" * 50)

        current_dir = os.getcwd()
        print(f"📁 Текущая директория: {current_dir}")
        print(f"📁 Содержимое: {os.listdir(current_dir)}")

        assets_path = os.path.join(current_dir, 'assets')
        print(f"📁 Путь к assets: {assets_path}")
        print(f"📁 Существует: {os.path.exists(assets_path)}")

        if os.path.exists(assets_path):
            print(f"📁 Содержимое assets: {os.listdir(assets_path)}")
            
            # Проверка прав
            test_file = os.path.join(assets_path, 'test_write.txt')
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                print("✅ Права на запись: OK")
                os.remove(test_file)
            except Exception as e:
                print(f"❌ Права на запись: {e}")
        else:
            print("❌ Папка assets не существует, создаем...")
            os.makedirs(assets_path)
            print("✅ Папка assets создана")

        print("=" * 50)
        
        # Создаем папку assets если она не существует
        ensure_assets_folder()
        
        print("=" * 50)
        print("🤖 ЗАПУСК БОТА-АВТООТВЕТЧИКА")
        print("🆕 С УНИВЕРСАЛЬНОЙ СИСТЕМОЙ КОМАНД")
        print("=" * 50)
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        # СНАЧАЛА регистрируем обработчики сообщений (они должны быть ПЕРВЫМИ)
        print("📝 Регистрируем обработчики сообщений...")
        application.add_handler(MessageHandler(
            filters.TEXT | filters.CAPTION | filters.PHOTO | filters.Document.ALL, 
            handle_group_message
        ))
        application.add_handler(MessageHandler(
            filters.TEXT | filters.CAPTION | filters.PHOTO | filters.Document.ALL,
            handle_private_message
        ))
        
        # ПОТОМ регистрируем ВСЕ кастомные команды
        print("📝 Регистрируем кастомные команды...")
        custom_commands_manager.register_all_handlers()
        
        # ЗАТЕМ основные команды бота
        print("📝 Регистрируем основные команды бота...")
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("check_files", check_files_command))
        
        # Команды для управления кастомными командами
        application.add_handler(CommandHandler("create_command", create_command_command))
        application.add_handler(CommandHandler("edit_command", edit_command_command))
        application.add_handler(CommandHandler("delete_command", delete_command_command))
        application.add_handler(CommandHandler("list_commands", list_commands_command))
        
        # Обработчики для создания команд
        application.add_handler(MessageHandler(
            filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO,
            handle_file_for_command
        ))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_for_command
        ))
        
        # Команды для управления воронками
        application.add_handler(CommandHandler("funnels", funnels_command))
        application.add_handler(CommandHandler("set_funnel_1", set_funnel_1_command))
        application.add_handler(CommandHandler("set_funnel_2", set_funnel_2_command))
        application.add_handler(CommandHandler("set_funnel_3", set_funnel_3_command))
        application.add_handler(CommandHandler("reset_funnels", reset_funnels_command))
        application.add_handler(CommandHandler("force_update_funnels", force_update_funnels_command))
        
        # Команды для обновления уведомления
        application.add_handler(CommandHandler("update_notification", update_notification_command))
        application.add_handler(CommandHandler("test_notification", test_notification_command))
        
        # Команды для управления исключениями
        application.add_handler(CommandHandler("add_exception", add_exception_command))
        application.add_handler(CommandHandler("remove_exception", remove_exception_command))
        application.add_handler(CommandHandler("list_exceptions", list_exceptions_command))
        application.add_handler(CommandHandler("clear_exceptions", clear_exceptions_command))
        
        # Команды для ручного управления сообщениями
        application.add_handler(CommandHandler("clear_chat", clear_chat_command))
        application.add_handler(CommandHandler("clear_all", clear_all_command))
        application.add_handler(CommandHandler("pending", pending_command))
        
        # Другие основные команды
        application.add_handler(CommandHandler("set_work_chat", set_work_chat_command))
        application.add_handler(CommandHandler("managers", managers_command))
        application.add_handler(CommandHandler("stats", stats_command))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Периодическая проверка и отправка нового уведомления (каждые 15 минут)
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(check_and_send_new_notification, interval=900, first=10)  # 15 минут
            print("✅ Планировщик задач запущен (удаление старого + отправка нового каждые 15 минут)")
            print("🛡️  COOLDOWN АКТИВИРОВАН - защита от частых отправок")
            print("🔧 ЛОГИКА ВОРОНОК: Без дублирования (1 чат = 1 воронка)")
            print("🆕 СИСТЕМА КОМАНД: Создавайте любые команды!")
        else:
            print("❌ Планировщик задач недоступен")
        
        # Запуск
        FUNNELS = funnels_config.get_funnels()
        excluded_users = excluded_users_manager.get_all_excluded()
        total_excluded = len(excluded_users["user_ids"]) + len(excluded_users["usernames"])
        custom_commands = custom_commands_manager.get_all_commands()
        
        print("🚀 Бот запускается...")
        print(f"📊 Загружено флагов: {flags_manager.count_flags()}")
        print(f"📋 Непрочитанных сообщений: {len(pending_messages_manager.get_all_pending_messages())}")
        print(f"👥 Менеджеров в системе: {total_excluded}")
        print(f"🆕 Кастомных команд: {len(custom_commands)}")
        print(f"⚙️ Воронки уведомлений: {FUNNELS}")
        
        if work_chat_manager.is_work_chat_set():
            print(f"💬 Рабочий чат установлен: {work_chat_manager.get_work_chat_id()}")
        else:
            print("⚠️ Рабочий чат не установлен! Используйте /set_work_chat")
        
        print("🔄 Логика уведомлений: УДАЛЕНИЕ СТАРОГО + ОТПРАВКА НОВОГО каждые 15 минут")
        print("⏳ COOLDOWN: 15 минут между отправками")
        print("🔧 ЛОГИКА ВОРОНОК: без дублирования (1 чат = 1 воронка)")
        print("🆕 КАСТОМНЫЕ КОМАНДЫ: текст, фото, документы, видео, аудио")
        print("⏰ Ожидание сообщений...")
        print("=" * 50)
        
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            close_loop=False
        )
        
    except Exception as e:
        print(f"💥 КРИТИЧЕСКАЯ ОШИБКА: {e}")
        logger.error(f"💥 Критическая ошибка при запуске бота: {e}")
        import traceback
        logger.error(f"💥 Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    main()

