def dashboard_navigation(request):
    match = request.resolver_match
    name = match.url_name if match else None
    sections = {
        'dashboard': 'overview',
        'assigned_tests': 'tests', 'test_roster': 'tests', 'take_test': 'tests', 'organise_test': 'tests',
        'student_directory': 'students', 'add_student': 'students',
        'edit_student': 'students', 'update_student_access': 'students', 'student_progress': 'students',
        'add_test': 'assign', 'student_courses': 'courses', 'learning_progress': 'progress',
        'gradebook': 'gradebook', 'to_do': 'tasks', 'student_calendar': 'calendar',
        'import_students': 'students', 'import_template': 'students',
        'course_workspace': 'materials', 'course_lesson': 'materials', 'course_practice': 'materials',
        'content_folder': 'materials', 'content_detail': 'materials', 'content_create': 'materials',
        'content_edit': 'materials', 'content_move': 'materials',
    }
    context = {'nav_section': sections.get(name)}
    if request.user.is_authenticated:
        from .views import my_courses
        slug = 'statistics' if name == 'course_practice' else match.kwargs.get('slug') if match else None
        course_id = request.GET.get('course', '')
        if slug:
            context['workspace_course'] = my_courses(request.user).select_related('teacher').filter(slug=slug).first()
        elif course_id.isdigit() and name not in {'dashboard', 'student_courses', 'password'}:
            context['workspace_course'] = my_courses(request.user).select_related('teacher').filter(pk=course_id).first()
    return context
