VAR drink = ""
VAR food = ""
VAR total = 0
VAR paid = false

EXTERNAL play(sound)
LIST sizes = small, medium, large

=== start ===
Официант: Здравствуйте! Сколько вас?
+ Один -> seat.one
+ Двое -> seat.two
+ Уйти -> leave.start

=== seat ===
== one ==
Официант: Отлично, проходите. Хотите меню на русском или на английском?
+ На русском -> seat.lang_ru
+ На английском -> seat.lang_en
+ Назад -> start

== two ==
Официант: Столик на двоих готов. Хотите начать с напитков или с еды?
+ Напитки -> drinks.menu
+ Еда -> food.menu
+ Назад -> start

== lang_ru ==
Официант: Меню на русском. С чего начнём: напитки или еда?
+ Напитки -> drinks.menu
+ Еда -> food.menu
+ Назад -> seat.one

== lang_en ==
Официант: Menu in English. Start with drinks or food?
+ Drinks -> drinks.menu
+ Food -> food.menu
+ Back -> seat.one

=== drinks ===
== menu ==
Бариста: Напитки <> чай (50), кофе (70), вода (30). Что хотите?
+ Чай -> tea
+ Кофе -> coffee
+ Вода -> water
+ Назад -> start

== tea ==
~ drink = "чай"
~ total = total + 50
~ play("ding")
Бариста: Чай добавлен. Хотите заказать еду?
+ Да, показать еду -> food.menu
+ Нет, перейти к подтверждению -> confirm.start
+ Назад к напиткам -> drinks.menu

== coffee ==
~ drink = "кофе"
~ total = total + 70
~ play("ding")
Бариста: Кофе добавлен. Хотите еду?
+ Да -> food.menu
+ Нет -> confirm.start
+ Назад к напиткам -> drinks.menu

== water ==
~ drink = "вода"
~ total = total + 30
~ play("ding")
Бариста: Вода добавлена. Хотите еду?
+ Да -> food.menu
+ Нет -> confirm.start
+ Назад к напиткам -> drinks.menu

=== food ===
== menu ==
Официант: Еда: сендвич (120), суп (150), десерт (80). Что выбрать?
+ Сендвич -> sandwich
+ Суп -> soup
+ Десерт -> dessert
+ Ничего -> none
+ Назад -> drinks.menu

== sandwich ==
~ food = "сендвич"
~ total = total + 120
Официант: Сендвич добавлен. Ещё что-то?
+ Да, посмотреть напитки -> drinks.menu
+ Нет, к подтверждению -> confirm.start
+ Назад к еде -> food.menu

== soup ==
~ food = "суп"
~ total = total + 150
Официант: Суп добавлен. Ещё что-то?
+ Да, напитки -> drinks.menu
+ Нет, к подтверждению -> confirm.start
+ Назад -> food.menu

== dessert ==
~ food = "десерт"
~ total = total + 80
Официант: Десерт добавлен. Ещё что-то?
+ Да, напитки -> drinks.menu
+ Нет, к подтверждению -> confirm.start
+ Назад -> food.menu

== none ==
Официант: Хорошо, без еды. Перейти к подтверждению?
+ Да -> confirm.start
+ Нет, вернуться к еде -> food.menu

=== confirm ===
== start ==
Официант: Ваш заказ: {drink != "" ? drink : "без напитка"}{food != "" ? " + " + food : ""}. Сумма {total} руб. Подтвердить?
+ Да, подтвердить -> payment.start
+ Нет, изменить -> start
+ Назад -> start

=== payment ===
== start ==
Официант: Оплатите сейчас?
+ Да, оплатить -> pay.method
+ Нет, оплачу позже -> END
+ Назад -> confirm.start

=== pay ===
== method ==
Официант: Как будете платить?
+ Наличными -> pay.cash
+ Картой -> pay.card
+ Назад -> payment.start

== cash ==
~ paid = true
Официант: Оплата наличными прошла. Спасибо!
-> END

== card ==
~ paid = true
Официант: Оплата картой прошла. Спасибо!
-> END

=== leave ===
== start ==
Официант: До свидания!
-> END
