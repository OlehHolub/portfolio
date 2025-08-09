# Makefile

# Справка по доступным командам
help:
	@echo "Доступные команды:"
	@echo "  make init      - Инициализация проекта (создание .env, если его нет)"
	@echo "  make up        - Запуск всех контейнеров"
	@echo "  make down      - Остановка всех контейнеров"
	@echo "  make restart   - Перезапуск всех контейнеров"
	@echo "  make logs      - Просмотр логов"
	@echo "  make test      - Запуск тестов"
	@echo "  make cleanup   - Очистка неиспользуемых данных Docker"
    #@echo "  make restart_hard   - Перезапуск всех контейнеров с удалением томов Применять осторожно"
	@echo "  make delete <имя контейнера>  - Удаление контейнера с образом и связанными томами"
	@echo "  make up-container <имя контейнера> - Создание и запуск определенного контейнера"
	@echo "  make update-container <имя контейнера> - Перезапускаем контейнер с обновлениями"

# Переменные окружения
ENV_FILE=.env
ENV_EXAMPLE_FILE=.env.example

# Команда для инициализации проекта
init:
	@if [ ! -f $(ENV_FILE) ]; then \
		echo "Файл $(ENV_FILE) не найден. Копирую из $(ENV_EXAMPLE_FILE)..."; \
		cp $(ENV_EXAMPLE_FILE) $(ENV_FILE); \
		if [ -f $(ENV_FILE) ]; then \
			echo "Файл $(ENV_FILE) создан. Отредактируйте его перед запуском проекта!"; \
		fi; \
	else \
		echo "Файл $(ENV_FILE) уже существует. Пропускаю шаг создания."; \
	fi

# Запуск всех контейнеров
up:
	docker-compose build --no-cache; \
	docker-compose up -d || echo "Ошибка запуска. Проверьте docker-compose.yml!"

# Остановка всех контейнеров
down:
	docker-compose down --rmi all

# Перезапуск всех контейнеров
restart: down up

# Перезапуск всех контейнеров с удалением томов. Применять осторожно! Потеря данных!
restart_hard: 
	docker-compose down -v
	docker-compose up --build || echo "Ошибка запуска. Проверьте docker-compose.yml!"

# Просмотр логов
logs:
	docker-compose logs -f

# Запуск тестов
test:
	pytest --cov=app tests/

# Очистка неиспользуемых данных Docker
cleanup:
	docker system prune -f
	docker volume prune -f
	docker network prune -f


.PHONY: delete

delete:
	@if [ -z "$(filter-out $@,$(MAKECMDGOALS))" ]; then \
		echo "Ошибка: Не указано имя контейнера. Использование: make delete <имя_контейнера>"; \
		exit 1; \
	fi; \
	CONTAINER=$(filter-out $@,$(MAKECMDGOALS)); \
	echo "Останавливаем и удаляем контейнер $$CONTAINER..."; \
	if docker ps -a --format '{{.Names}}' | grep -w "^$$CONTAINER$$" > /dev/null; then \
		docker rm -f $$CONTAINER; \
	else \
		echo "Контейнер $$CONTAINER не найден."; \
	fi; \
	echo "Удаляем связанные тома, которые не используются другими контейнерами..."; \
	VOLUMES=$$(docker volume ls --filter name=$$CONTAINER --format '{{.Name}}'); \
	for VOLUME in $$VOLUMES; do \
		USING_CONTAINERS=$$(docker ps -a --filter volume=$$VOLUME --format '{{.Names}}'); \
		if [ -z "$$USING_CONTAINERS" ]; then \
			echo "Удаляем том: $$VOLUME"; \
			docker volume rm $$VOLUME || true; \
		else \
			echo "Том $$VOLUME используется другими контейнерами и не будет удалён."; \
		fi; \
	done; \
	echo "Удаляем связанный образ..."; \
	IMAGE=$$(docker inspect --format='{{.Config.Image}}' $$CONTAINER 2>/dev/null); \
	if [ -n "$$IMAGE" ]; then \
		docker rmi -f $$IMAGE || true; \
	else \
		echo "Нет связанного образа для контейнера $$CONTAINER."; \
	fi; \
	echo "Удаляем все оставшиеся неиспользуемые тома..."; \
	docker volume prune -f


.PHONY: up-container

up-container:
	@if [ -z "$(filter-out $@,$(MAKECMDGOALS))" ]; then \
		echo "Ошибка: Не указано имя контейнера. Использование: make up-container <имя_сервиса>"; \
		exit 1; \
	fi; \
	echo "Собираем контейнер $(filter-out $@,$(MAKECMDGOALS))..."; \
	docker-compose build $(filter-out $@,$(MAKECMDGOALS)) >/dev/null 2>&1; \
	CONTAINER=$(filter-out $@,$(MAKECMDGOALS)); \
	if [ -n "$$(docker ps -q -f name=$$CONTAINER)" ]; then \
		echo "Контейнер $$CONTAINER уже запущен."; \
	else \
		echo "Запускаем контейнер $$CONTAINER..."; \
		docker-compose up -d $$CONTAINER >/dev/null 2>&1; \
	fi

.PHONY: update-container

update-container:
	@if [ -z "$(filter-out $@,$(MAKECMDGOALS))" ]; then \
		echo "Ошибка: Не указано имя контейнера. Использование: make update-container <имя_сервиса>"; \
		exit 1; \
	fi; \
	SERVICE=$(filter-out $@,$(MAKECMDGOALS)); \
	echo "Останавливаем контейнер $$SERVICE..."; \
	docker-compose stop $$SERVICE; \
	echo "Удаляем контейнер $$SERVICE..."; \
	docker-compose rm -fs $$SERVICE; \
	echo "Пересобираем образ для $$SERVICE..."; \
	docker-compose build $$SERVICE; \
	echo "Запускаем контейнер $$SERVICE..."; \
	docker-compose up -d $$SERVICE;

.PHONY: clean-unused

clean-unused:
	@echo "Удаляем все неиспользуемые контейнеры..."
	docker container prune -f
	@echo "Удаляем все неиспользуемые образы..."
	docker image prune -f
	@echo "Удаляем все неиспользуемые тома..."
	docker volume prune -f
	@echo "Удаляем все неиспользуемые сети..."
	docker network prune -f
	@echo "Очистка завершена! Все используемые ресурсы остаются нетронутыми."


%:
	@:
