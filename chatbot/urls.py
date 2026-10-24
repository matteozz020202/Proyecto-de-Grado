from django.urls import path
from . import views

app_name = 'chatbot'
urlpatterns = [
    path('state/', views.state, name='state'),
    path('message/', views.message, name='message'),
    path('select/', views.select, name='select'),
    path('reset/', views.reset, name='reset'),
    path('resume/', views.resume, name='resume'),
]
