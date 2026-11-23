from django.urls import path

from . import api

urlpatterns = [
    path("inventory/items/", api.ItemListCreateView.as_view()),
    path("inventory/items/<uuid:pk>/", api.ItemDetailView.as_view()),
    path("inventory/suppliers/", api.SupplierListCreateView.as_view()),
    path("inventory/suppliers/<uuid:pk>/", api.SupplierDetailView.as_view()),
    path("inventory/purchases/", api.PurchaseListCreateView.as_view()),
    path("inventory/movements/", api.MovementListCreateView.as_view()),
    path("inventory/alerts/", api.StockAlertsView.as_view()),
]
