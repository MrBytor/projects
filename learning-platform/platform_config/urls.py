from django.conf import settings
from django.contrib.auth.views import LogoutView
from django.urls import path
from django.views.static import serve
from learning import views
from learning import lms_views
from learning import workspace_views
from learning import material_views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.PlatformLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('password/', views.password, name='password'),
    path('assigned-tests/', views.assigned_tests, name='assigned_tests'),
    path('my-courses/', views.student_courses, name='student_courses'),
    path('courses/statistics/practice/', workspace_views.course_practice, name='course_practice'),
    path('courses/<slug:slug>/', workspace_views.course_workspace, name='course_workspace'),
    path('courses/<slug:slug>/folders/<int:pk>/', material_views.content_folder, name='content_folder'),
    path('courses/<slug:slug>/materials/new/', material_views.content_create, name='content_create'),
    path('courses/<slug:slug>/materials/<int:pk>/', material_views.content_detail, name='content_detail'),
    path('courses/<slug:slug>/materials/<int:pk>/edit/', material_views.content_edit, name='content_edit'),
    path('courses/<slug:slug>/materials/<int:pk>/move/', material_views.content_move, name='content_move'),
    path('courses/<slug:slug>/materials/<int:pk>/reorder/', material_views.content_reorder, name='content_reorder'),
    path('courses/<slug:slug>/materials/<int:pk>/visibility/', material_views.content_visibility, name='content_visibility'),
    path('courses/<slug:slug>/materials/<int:pk>/download/', material_views.content_download, name='content_download'),
    path('courses/<slug:slug>/materials/<int:pk>/video/', material_views.content_video, name='content_video'),
    path('courses/<slug:slug>/materials/<int:pk>/slides/<int:number>/', material_views.content_slide, name='content_slide'),
    path('courses/<slug:slug>/classes/<slug:key>/', workspace_views.course_lesson, name='course_lesson'),
    path('courses/<slug:slug>/classes/<slug:key>/materials/<int:index>/', workspace_views.lesson_material, name='lesson_material'),
    path('courses/<slug:slug>/classes/<slug:key>/slides/<int:index>/<int:number>/', workspace_views.lesson_slide, name='lesson_slide'),
    path('learning-progress/', views.learning_progress, name='learning_progress'),
    path('my-tasks/', lms_views.to_do, name='to_do'),
    path('calendar/', lms_views.student_calendar, name='student_calendar'),
    path('teacher/gradebook/', lms_views.gradebook, name='gradebook'),
    path('teacher/students/', views.student_directory, name='student_directory'),
    path('teacher/students/import/', lms_views.import_students, name='import_students'),
    path('teacher/students/import/template/', lms_views.import_template, name='import_template'),
    path('teacher/students/new/', views.add_student, name='add_student'),
    path('teacher/students/<int:pk>/edit/', views.edit_student, name='edit_student'),
    path('teacher/students/<int:pk>/courses/', views.update_student_access, name='update_student_access'),
    path('teacher/tests/new/', views.add_test, name='add_test'),
    path('teacher/tests/<int:pk>/', views.assignment_roster, name='test_roster'),
    path('teacher/tests/<int:pk>/organise/', views.organise_test, name='organise_test'),
    path('tests/<int:pk>/', views.take_test, name='take_test'),
    path('teacher/homework/new/', views.add_assignment, name='add_assignment'),
    path('teacher/students/<int:pk>/', views.student_progress, name='student_progress'),
    path('homework/<int:pk>/', views.assignment, name='assignment'),
    path('teacher/review/<int:pk>/', views.review, name='review'),
    path('api/practice/attempt/', views.practice_attempt),
    path('api/session/', views.session_status),
    path('site/', views.course_site),
    path('site/<path:asset>', views.course_site),
    path('platform-assets/<path:path>', serve, {'document_root': settings.BASE_DIR / 'assets'}),
    path('design-assets/<path:path>', serve, {'document_root': settings.SITE_DIR / 'assets'}),
]
