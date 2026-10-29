"""
Своя таблица кабинета одна: связь «преподаватель в расписании ↔ сотрудник в Гауди».

В расписании у преподавателя только имя (Lector.name), ID из Гауди там нет. Кабинет связывает сам
по ФИО при входе преподавателя (auto=True); кого не нашёл — связывает ИО на странице /io/lectors/.
"""
from django.db import models


class LectorLink(models.Model):
    lector_id = models.PositiveIntegerField("преподаватель в расписании (id)", unique=True)
    lector_name = models.CharField("имя в расписании", max_length=100)
    staff_id = models.PositiveIntegerField("ID сотрудника в Гауди", db_index=True)
    staff_name = models.CharField("ФИО в Гауди", max_length=200)
    auto = models.BooleanField("найден по ФИО автоматически", default=False)
    linked_by = models.CharField("кто связал", max_length=200, blank=True)
    linked_at = models.DateTimeField("когда", auto_now=True)

    def __str__(self):
        return "%s → %s" % (self.lector_name, self.staff_id)
