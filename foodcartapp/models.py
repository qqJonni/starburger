import re

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from phonenumber_field.modelfields import PhoneNumberField
from geopy import distance
from requests import HTTPError

from foodcartapp.get_geo import fetch_coordinates
from star_burger import settings


class Restaurant(models.Model):
    name = models.CharField(
        'название',
        max_length=50
    )
    address = models.CharField(
        'адрес',
        max_length=100,
        blank=True,
    )
    contact_phone = models.CharField(
        'контактный телефон',
        max_length=50,
        blank=True,
    )

    class Meta:
        verbose_name = 'ресторан'
        verbose_name_plural = 'рестораны'

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def available(self):
        products = (
            RestaurantMenuItem.objects
            .filter(availability=True)
            .values_list('product')
        )
        return self.filter(pk__in=products)


class ProductCategory(models.Model):
    name = models.CharField(
        'название',
        max_length=50
    )

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'категории'

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(
        'название',
        max_length=50
    )
    category = models.ForeignKey(
        ProductCategory,
        verbose_name='категория',
        related_name='products',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    price = models.DecimalField(
        'цена',
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    image = models.ImageField(
        'картинка'
    )
    special_status = models.BooleanField(
        'спец.предложение',
        default=False,
        db_index=True,
    )
    description = models.TextField(
        'описание',
        max_length=200,
        blank=True,
    )

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = 'товар'
        verbose_name_plural = 'товары'

    def __str__(self):
        return self.name


class RestaurantMenuItem(models.Model):
    restaurant = models.ForeignKey(
        Restaurant,
        related_name='menu_items',
        verbose_name="ресторан",
        on_delete=models.CASCADE,
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='menu_items',
        verbose_name='продукт',
    )
    availability = models.BooleanField(
        'в продаже',
        default=True,
        db_index=True
    )

    class Meta:
        verbose_name = 'Пункт меню ресторана'
        verbose_name_plural = 'Пункты меню ресторана'
        unique_together = [
            ['restaurant', 'product']
        ]

    def __str__(self):
        return f"{self.restaurant.name} - {self.product.name}"


class Place(models.Model):
    name = models.CharField(
        'название',
        max_length=400,
        db_index=True,
        unique=True,
    )
    lon = models.FloatField(
        'широта'
    )
    lat = models.FloatField(
        'долгота'
    )

    class Meta:
        verbose_name = 'место'
        verbose_name_plural = 'места'


def atoi(text):
    return int(text) if text.isdigit() else text


def natural_keys(text):
    """
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    """
    return [atoi(c) for c in re.split(r'[+-]?([0-9]+(?:[.][0-9]*)?|[.][0-9]+)', text)]


def get_place_coordinates(api_key, place):
    try:
        place = get_object_or_404(Place, name=place)
        lon, lat = place.lon, place.lat
        return lon, lat
    except Http404:
        lon, lat = fetch_coordinates(api_key, place)
        Place.objects.create(name=place, lon=lon, lat=lat)
        return lon, lat


def get_distance(apikey, place_from, place_to):
    """
    Возвращает расстояние между двумя точками в км
    :param apikey: ключ для yandex api
    :param place_from: начальная точка
    :param place_to: конечная точка
    :return: расстояние в км
    """
    try:
        coords_from = get_place_coordinates(apikey, place_from)
        coords_to = get_place_coordinates(apikey, place_to)
        dist = distance.distance(coords_from, coords_to).km
        return dist
    except HTTPError as e:
        return 0


class OrderQuerySet(models.QuerySet):
    def prefetch_items(self):
        apikey = settings.YANDEX_KEY
        orders = Order.objects.exclude(status=Order.READY).order_by('-status').select_related(
            'restaurant').prefetch_related('items', 'items__product').annotate(product_count=Count('items__product'))

        menu_items = RestaurantMenuItem.objects.filter(availability=True).values('restaurant', 'product')
        restaurants = Restaurant.objects.in_bulk([item['restaurant'] for item in menu_items])

        for order in orders:
            if order.restaurant is None:
                order_restaurants = []
                order_products = order.items.all()
                for restaurant in restaurants:
                    restaurants_possible = True
                    for order_product in order_products:
                        restaurants_for_product = menu_items.filter(product=order_product.product,
                                                                    restaurant=restaurants[restaurant])
                        if not restaurants_for_product:
                            restaurants_possible = False
                    if restaurants_possible:
                        div_distance = get_distance(apikey, order.address, restaurants[restaurant].address)
                        order_restaurants.append({
                            'restaurant': restaurants[restaurant],
                            'distance': div_distance
                        })
                delivery_restaurants = []
                if order_restaurants:
                    for restaurant in order_restaurants:
                        div_distance = restaurant['distance']
                        restaurant["restaurant"].distance = div_distance
                        delivery_restaurants.append(f'{restaurant["restaurant"].name} - {round(div_distance, 0)}')
                delivery_restaurants.sort(key=natural_keys)
                order.restaurant_possible = delivery_restaurants
        return orders


class Order(models.Model):
    CASH = 'CASH'
    ELECTRONICALLY = 'ELECTRON'
    PAY_TYPE = [
        (CASH, 'Наличными'),
        (ELECTRONICALLY, 'Электронно'),
    ]
    pay = models.CharField(
        'Способ оплаты',
        choices=PAY_TYPE,
        max_length=20,
        db_index=True,

    )

    NEW = 'new'
    COOKING = 'cooking'
    DELIVERY = 'delivery'
    READY = 'ready'
    ORDER_STATUS = [
        (NEW, 'Необработанный'),
        (COOKING, 'Готовится'),
        (DELIVERY, 'Доставка'),
        (READY, 'Доставлен'),
    ]
    status = models.CharField(
        'Статус заказа',
        choices=ORDER_STATUS,
        default=NEW,
        max_length=20,
        db_index=True
    )
    firstname = models.CharField(
        'Имя',
        max_length=90
    )
    lastname = models.CharField(
        'Фамилия',
        max_length=100,
        db_index=True
    )

    phonenumber = PhoneNumberField(
        verbose_name='Телефон',
        db_index=True
    )

    address = models.CharField(
        'Адрес доставки',
        max_length=100,
    )
    total_price = models.DecimalField(
        'Сумма заказа',
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(
            limit_value=0
        )])
    comment = models.TextField(
        blank=True, verbose_name='Комментарий к заказу'
    )
    registration_date = models.DateTimeField(
        blank=True, null=True, verbose_name='Дата регистрации', db_index=True, auto_now=True
    )
    call_date = models.DateTimeField(
        blank=True, null=True, verbose_name='Дата звонка', db_index=True
    )
    delivery_date = models.DateTimeField(
        blank=True, null=True, verbose_name='Дата доставки', db_index=True
    )

    restaurant = models.ForeignKey(
        Restaurant,
        verbose_name='Ресторан',
        blank=True,
        null=True,
        on_delete=models.CASCADE
    )
    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'

    def __str__(self):
        return f'{self.firstname} {self.phone_number}'

    def get_total_cost(self):
        # общая сумма заказа
        return sum(item.get_cost() for item in self.items.all())

    @staticmethod
    def prefetch_products():
        menu_items = RestaurantMenuItem.objects.filter(availability=True)


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        related_name='items',
        verbose_name="Заказы",
        on_delete=models.CASCADE,
    )
    product = models.ForeignKey(
        Product,
        related_name='products',
        verbose_name="Продукты",
        on_delete=models.CASCADE,
    )
    quantity = models.IntegerField('Количество',
                                   validators=[
                                       MaxValueValidator(100),
                                       MinValueValidator(1)
                                   ]
                                   )
    price = models.DecimalField(
        'Сумма',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(
            limit_value=0
        )],
    )

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        unique_together = ('order', 'product')

    def __str__(self):
        return f"{self.order.phone_number} - {self.product.name}"

    def get_cost(self):
        return self.product.price * self.quantity
