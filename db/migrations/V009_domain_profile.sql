CREATE TABLE `domain_profile` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `domain_id` bigint unsigned NOT NULL,

  -- Human-authored, stable inputs
  `summary` text NULL,                       -- plain-English summary (short)
  `keywords` json NULL,                      -- ["attendance","chronic absenteeism","ADA",...]
  `entities` json NULL,                      -- ["student","school","calendar_date",...]
  `metrics` json NULL,                       -- ["attendance_rate","absences_count",...]
  `attributes` json NULL,                    -- ["student_id","school_id","attendance_date",...]
  `synonyms` json NULL,                      -- [{"term":"sped","means":["special education"]}, ...]
  `acronyms` json NULL,                      -- [{"abbr":"ADA","expansion":"Average Daily Attendance"}, ...]
  `notes` text NULL,                         -- anything else helpful

  -- Deterministic “what we embed”
  `embedding_text` mediumtext NOT NULL,       -- generated from above, or authored directly
  `content_hash` char(64) NOT NULL,           -- sha256 of embedding_text
  `embedding_model` varchar(128) DEFAULT NULL,
  `embedded_at` timestamp NULL DEFAULT NULL,

  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_domain_profile` (`workspace_id`,`domain_id`),
  KEY `ix_domain_profile_ws` (`workspace_id`),
  KEY `ix_domain_profile_domain` (`domain_id`),
  CONSTRAINT `fk_domain_profile_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_domain_profile_ws` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

/* ============================================================
   Domain Profiles Seed
   Workspace: 927164193773577
   Purpose: Canonical domain metadata + embedding source
   ============================================================ */

INSERT INTO domain_profile (
  workspace_id,
  domain_id,
  summary,
  keywords,
  entities,
  attributes,
  metrics,
  synonyms,
  acronyms,
  notes,
  embedding_text,
  content_hash
)
VALUES

/* ============================================================
   4) Schools, Districts & Organizations
   ============================================================ */
(
  '927164193773577',
  4,
  'Organizational structure and attributes for districts, schools, and education organizations.',
  JSON_ARRAY(
    'schools','districts','education organizations','organization hierarchy',
    'school directory','school attributes','district attributes',
    'school codes','district codes'
  ),
  JSON_ARRAY(
    'education_organization','district','school','charter','location','address'
  ),
  JSON_ARRAY(
    'education_organization_id','school_id','district_id',
    'school_code','district_code','school_name','district_name',
    'school_type','grade_span','address','city','state','zip','phone'
  ),
  JSON_ARRAY(
    'enrollment_count_by_school','staff_count_by_school'
  ),
  JSON_ARRAY(
    JSON_OBJECT('term','org','means',JSON_ARRAY('organization','education organization')),
    JSON_OBJECT('term','lea','means',JSON_ARRAY('district','local education agency'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','LEA','expansion','Local Education Agency'),
    JSON_OBJECT('abbr','SEA','expansion','State Education Agency')
  ),
  'Used for grouping and joins across student and staff domains.',
  'Domain: Schools, Districts & Organizations
Kind: Schools
Description: Organizational structure and attributes.

Purpose: Organization hierarchy and directory attributes for districts, schools, and education organizations.

Keywords: schools, districts, education organizations, organization hierarchy, school directory, school codes, district codes.

Entities: education_organization, district, school, charter, location, address.

Attributes: education_organization_id, school_id, district_id, school_code, district_code, school_name, district_name, school_type, grade_span, address, city, state, zip, phone.

Acronyms: LEA = Local Education Agency; SEA = State Education Agency.
Synonyms: org = organization; lea = district.

Excludes: students, attendance, grades, assessments, discipline.',
  SHA2(
    'Domain: Schools, Districts & Organizations
Kind: Schools
Description: Organizational structure and attributes.

Purpose: Organization hierarchy and directory attributes for districts, schools, and education organizations.

Keywords: schools, districts, education organizations, organization hierarchy, school directory, school codes, district codes.

Entities: education_organization, district, school, charter, location, address.

Attributes: education_organization_id, school_id, district_id, school_code, district_code, school_name, district_name, school_type, grade_span, address, city, state, zip, phone.

Acronyms: LEA = Local Education Agency; SEA = State Education Agency.
Synonyms: org = organization; lea = district.

Excludes: students, attendance, grades, assessments, discipline.',
    256
  )
),

/* ============================================================
   5) Staff & Assignments
   ============================================================ */
(
  '927164193773577',
  5,
  'Staff identity, roles, and assignments to schools, courses, and sections.',
  JSON_ARRAY(
    'staff','teachers','educators','instructors',
    'staff assignments','teacher assignments',
    'staff roles','section assignments'
  ),
  JSON_ARRAY(
    'staff','teacher','school','district','section','course','assignment','position'
  ),
  JSON_ARRAY(
    'staff_id','staff_unique_id','state_staff_id',
    'first_name','last_name','email',
    'school_id','district_id',
    'position_title','role',
    'assignment_begin_date','assignment_end_date'
  ),
  JSON_ARRAY(
    'fte','teacher_count','staff_count'
  ),
  JSON_ARRAY(
    JSON_OBJECT('term','educator','means',JSON_ARRAY('teacher','instructor'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','FTE','expansion','Full-Time Equivalent')
  ),
  'Links staff to schools, courses, and instructional sections.',
  'Domain: Staff & Assignments
Kind: Staff
Description: Staff information and instructional assignments.

Purpose: Staff identity and school/section assignments, including roles and positions.

Keywords: staff, teachers, educators, instructors, staff assignments, teacher assignments, staff roles.

Entities: staff, teacher, school, district, section, course, assignment, position.

Attributes: staff_id, staff_unique_id, state_staff_id, first_name, last_name, email, school_id, district_id, position_title, role, assignment_begin_date, assignment_end_date.

Metrics: FTE, teacher_count, staff_count.
Acronyms: FTE = Full-Time Equivalent.

Excludes: student demographics, attendance, grades, discipline.',
  SHA2(
    'Domain: Staff & Assignments
Kind: Staff
Description: Staff information and instructional assignments.

Purpose: Staff identity and school/section assignments, including roles and positions.

Keywords: staff, teachers, educators, instructors, staff assignments, teacher assignments, staff roles.

Entities: staff, teacher, school, district, section, course, assignment, position.

Attributes: staff_id, staff_unique_id, state_staff_id, first_name, last_name, email, school_id, district_id, position_title, role, assignment_begin_date, assignment_end_date.

Metrics: FTE, teacher_count, staff_count.
Acronyms: FTE = Full-Time Equivalent.

Excludes: student demographics, attendance, grades, discipline.',
    256
  )
),

/* ============================================================
   6) Students – Profile & Demographics
   ============================================================ */
(
  '927164193773577',
  6,
  'Student identity, demographics, and stable attributes used for reporting and segmentation.',
  JSON_ARRAY(
    'student profile','student demographics','student identity',
    'student attributes','student characteristics','student segmentation'
  ),
  JSON_ARRAY(
    'student','person','guardian','household'
  ),
  JSON_ARRAY(
    'student_id','state_student_id','local_student_id',
    'first_name','last_name','date_of_birth',
    'sex','gender','race','ethnicity',
    'language','home_language',
    'address','city','state','zip','phone','email'
  ),
  JSON_ARRAY(),
  JSON_ARRAY(
    JSON_OBJECT('term','sped','means',JSON_ARRAY('special education')),
    JSON_OBJECT('term','lep','means',JSON_ARRAY('english learner','limited english proficient'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','EL','expansion','English Learner'),
    JSON_OBJECT('abbr','ELL','expansion','English Language Learner'),
    JSON_OBJECT('abbr','IEP','expansion','Individualized Education Program'),
    JSON_OBJECT('abbr','FRPL','expansion','Free or Reduced-Price Lunch')
  ),
  'Stable student attributes. Excludes enrollment and attendance.',
  'Domain: Students – Profile & Demographics
Kind: Student
Description: Student identity, demographics, and stable attributes.

Purpose: Student-level identifiers and demographic attributes used for joins and segmentation.

Keywords: student profile, student demographics, student identity, student attributes.

Entities: student, person, guardian, household.

Attributes: student_id, state_student_id, local_student_id, first_name, last_name, date_of_birth, sex, gender, race, ethnicity, language, home_language, address, city, state, zip, phone, email.

Acronyms: EL, ELL, IEP, FRPL.
Synonyms: sped = special education; lep = english learner.

Excludes: enrollment, attendance, grades, discipline.',
  SHA2(
    'Domain: Students – Profile & Demographics
Kind: Student
Description: Student identity, demographics, and stable attributes.

Purpose: Student-level identifiers and demographic attributes used for joins and segmentation.

Keywords: student profile, student demographics, student identity, student attributes.

Entities: student, person, guardian, household.

Attributes: student_id, state_student_id, local_student_id, first_name, last_name, date_of_birth, sex, gender, race, ethnicity, language, home_language, address, city, state, zip, phone, email.

Acronyms: EL, ELL, IEP, FRPL.
Synonyms: sped = special education; lep = english learner.

Excludes: enrollment, attendance, grades, discipline.',
    256
  )
)

ON DUPLICATE KEY UPDATE
  summary        = VALUES(summary),
  keywords       = VALUES(keywords),
  entities       = VALUES(entities),
  attributes     = VALUES(attributes),
  metrics        = VALUES(metrics),
  synonyms       = VALUES(synonyms),
  acronyms       = VALUES(acronyms),
  notes          = VALUES(notes),
  embedding_text = VALUES(embedding_text),
  content_hash   = VALUES(content_hash),
  updated_at     = CURRENT_TIMESTAMP;

  /* ============================================================
   Domain Profiles Seed (UPSERT)
   Workspace: 927164193773577
   Table: domain_profile
   Requires: UNIQUE KEY (workspace_id, domain_id)
   ============================================================ */

INSERT INTO domain_profile (
  workspace_id,
  domain_id,
  summary,
  keywords,
  entities,
  attributes,
  metrics,
  synonyms,
  acronyms,
  notes,
  embedding_text,
  content_hash
)
VALUES

/* ============================================================
   4) Schools, Districts & Organizations
   ============================================================ */
(
  '927164193773577',
  4,
  'Organizational structure and attributes for districts, schools, and education organizations.',
  JSON_ARRAY(
    'schools','districts','education organizations','organization hierarchy',
    'school directory','school attributes','district attributes',
    'school codes','district codes'
  ),
  JSON_ARRAY('education_organization','district','school','charter','location','address'),
  JSON_ARRAY(
    'education_organization_id','school_id','district_id',
    'school_code','district_code','school_name','district_name',
    'school_type','grade_span','address','city','state','zip','phone'
  ),
  JSON_ARRAY('enrollment_count_by_school','staff_count_by_school'),
  JSON_ARRAY(
    JSON_OBJECT('term','org','means',JSON_ARRAY('organization','education organization')),
    JSON_OBJECT('term','lea','means',JSON_ARRAY('district','local education agency'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','LEA','expansion','Local Education Agency'),
    JSON_OBJECT('abbr','SEA','expansion','State Education Agency')
  ),
  'Used for grouping and joins across student and staff domains.',
  'Domain: Schools, Districts & Organizations
Kind: Schools
Description: Organizational structure and attributes.

Purpose: Organization hierarchy and directory attributes for districts, schools, and education organizations.

Keywords: schools, districts, education organizations, organization hierarchy, school directory, school codes, district codes.
Entities: education_organization, district, school, charter, location, address.
Attributes: education_organization_id, school_id, district_id, school_code, district_code, school_name, district_name, school_type, grade_span, address, city, state, zip, phone.

Acronyms: LEA = Local Education Agency; SEA = State Education Agency.
Synonyms: org = organization; lea = district.

Excludes: students, attendance, grades, assessments, discipline.',
  SHA2(
    'Domain: Schools, Districts & Organizations
Kind: Schools
Description: Organizational structure and attributes.

Purpose: Organization hierarchy and directory attributes for districts, schools, and education organizations.

Keywords: schools, districts, education organizations, organization hierarchy, school directory, school codes, district codes.
Entities: education_organization, district, school, charter, location, address.
Attributes: education_organization_id, school_id, district_id, school_code, district_code, school_name, district_name, school_type, grade_span, address, city, state, zip, phone.

Acronyms: LEA = Local Education Agency; SEA = State Education Agency.
Synonyms: org = organization; lea = district.

Excludes: students, attendance, grades, assessments, discipline.',
    256
  )
),

/* ============================================================
   5) Staff & Assignments
   ============================================================ */
(
  '927164193773577',
  5,
  'Staff identity, roles, and assignments to schools, courses, and sections.',
  JSON_ARRAY(
    'staff','teachers','educators','instructors',
    'staff assignments','teacher assignments',
    'staff roles','section assignments'
  ),
  JSON_ARRAY('staff','teacher','school','district','section','course','assignment','position'),
  JSON_ARRAY(
    'staff_id','staff_unique_id','state_staff_id',
    'first_name','last_name','email',
    'school_id','district_id',
    'position_title','role',
    'assignment_begin_date','assignment_end_date'
  ),
  JSON_ARRAY('fte','teacher_count','staff_count'),
  JSON_ARRAY(
    JSON_OBJECT('term','educator','means',JSON_ARRAY('teacher','instructor'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','FTE','expansion','Full-Time Equivalent')
  ),
  'Links staff to schools, courses, and instructional sections.',
  'Domain: Staff & Assignments
Kind: Staff
Description: Staff information and instructional assignments.

Purpose: Staff identity and school/section assignments, including roles and positions.

Keywords: staff, teachers, educators, instructors, staff assignments, teacher assignments, staff roles.
Entities: staff, teacher, school, district, section, course, assignment, position.
Attributes: staff_id, staff_unique_id, state_staff_id, first_name, last_name, email, school_id, district_id, position_title, role, assignment_begin_date, assignment_end_date.

Metrics: FTE, teacher_count, staff_count.
Acronyms: FTE = Full-Time Equivalent.

Excludes: student demographics, attendance, grades, discipline.',
  SHA2(
    'Domain: Staff & Assignments
Kind: Staff
Description: Staff information and instructional assignments.

Purpose: Staff identity and school/section assignments, including roles and positions.

Keywords: staff, teachers, educators, instructors, staff assignments, teacher assignments, staff roles.
Entities: staff, teacher, school, district, section, course, assignment, position.
Attributes: staff_id, staff_unique_id, state_staff_id, first_name, last_name, email, school_id, district_id, position_title, role, assignment_begin_date, assignment_end_date.

Metrics: FTE, teacher_count, staff_count.
Acronyms: FTE = Full-Time Equivalent.

Excludes: student demographics, attendance, grades, discipline.',
    256
  )
),

/* ============================================================
   6) Students – Profile & Demographics
   ============================================================ */
(
  '927164193773577',
  6,
  'Student identity, demographics, and stable attributes used for reporting and segmentation.',
  JSON_ARRAY(
    'student profile','student demographics','student identity',
    'student attributes','student characteristics','student segmentation'
  ),
  JSON_ARRAY('student','person','guardian','household'),
  JSON_ARRAY(
    'student_id','state_student_id','local_student_id',
    'first_name','last_name','date_of_birth',
    'sex','gender','race','ethnicity',
    'language','home_language',
    'address','city','state','zip','phone','email'
  ),
  JSON_ARRAY(),
  JSON_ARRAY(
    JSON_OBJECT('term','sped','means',JSON_ARRAY('special education')),
    JSON_OBJECT('term','lep','means',JSON_ARRAY('english learner','limited english proficient'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','EL','expansion','English Learner'),
    JSON_OBJECT('abbr','ELL','expansion','English Language Learner'),
    JSON_OBJECT('abbr','IEP','expansion','Individualized Education Program'),
    JSON_OBJECT('abbr','FRPL','expansion','Free or Reduced-Price Lunch')
  ),
  'Stable student attributes. Excludes enrollment and attendance.',
  'Domain: Students – Profile & Demographics
Kind: Student
Description: Student identity, demographics, and stable attributes.

Purpose: Student-level identifiers and demographic attributes used for joins and segmentation.

Keywords: student profile, student demographics, student identity, student attributes.
Entities: student, person, guardian, household.
Attributes: student_id, state_student_id, local_student_id, first_name, last_name, date_of_birth, sex, gender, race, ethnicity, language, home_language, address, city, state, zip, phone, email.

Acronyms: EL, ELL, IEP, FRPL.
Synonyms: sped = special education; lep = english learner.

Excludes: enrollment, attendance, grades, discipline.',
  SHA2(
    'Domain: Students – Profile & Demographics
Kind: Student
Description: Student identity, demographics, and stable attributes.

Purpose: Student-level identifiers and demographic attributes used for joins and segmentation.

Keywords: student profile, student demographics, student identity, student attributes.
Entities: student, person, guardian, household.
Attributes: student_id, state_student_id, local_student_id, first_name, last_name, date_of_birth, sex, gender, race, ethnicity, language, home_language, address, city, state, zip, phone, email.

Acronyms: EL, ELL, IEP, FRPL.
Synonyms: sped = special education; lep = english learner.

Excludes: enrollment, attendance, grades, discipline.',
    256
  )
),

/* ============================================================
   7) Enrollment
   ============================================================ */
(
  '927164193773577',
  7,
  'Student enrollment history and school associations over time.',
  JSON_ARRAY(
    'enrollment','student enrollment','enrollment history',
    'school association','entry date','exit date','withdrawal','mobility'
  ),
  JSON_ARRAY('student','school','district','enrollment','calendar','grade_level'),
  JSON_ARRAY(
    'enrollment_id','student_id','school_id','district_id',
    'entry_date','exit_date','exit_reason','entry_reason',
    'grade_level','school_year'
  ),
  JSON_ARRAY('enrollment_count','mobility_rate'),
  JSON_ARRAY(
    JSON_OBJECT('term','withdrawal','means',JSON_ARRAY('exit','transfer','leave school'))
  ),
  JSON_ARRAY(),
  'Time-bound enrollment records, including entry/exit and grade level.',
  'Domain: Enrollment
Kind: Enrollment
Description: Student enrollment history and school associations.

Purpose: Track when students enter/exit schools and districts, and grade level over time.

Keywords: enrollment, enrollment history, entry date, exit date, withdrawal, mobility.
Entities: student, school, district, enrollment, calendar, grade_level.
Attributes: enrollment_id, student_id, school_id, district_id, entry_date, exit_date, exit_reason, entry_reason, grade_level, school_year.
Metrics: enrollment_count, mobility_rate.

Excludes: daily attendance events, grades/transcripts, assessments, discipline.',
  SHA2(
    'Domain: Enrollment
Kind: Enrollment
Description: Student enrollment history and school associations.

Purpose: Track when students enter/exit schools and districts, and grade level over time.

Keywords: enrollment, enrollment history, entry date, exit date, withdrawal, mobility.
Entities: student, school, district, enrollment, calendar, grade_level.
Attributes: enrollment_id, student_id, school_id, district_id, entry_date, exit_date, exit_reason, entry_reason, grade_level, school_year.
Metrics: enrollment_count, mobility_rate.

Excludes: daily attendance events, grades/transcripts, assessments, discipline.',
    256
  )
),

/* ============================================================
   8) Attendance
   ============================================================ */
(
  '927164193773577',
  8,
  'Student attendance events and attendance-related metrics.',
  JSON_ARRAY(
    'attendance','student attendance','daily attendance',
    'absences','tardies','present','excused','unexcused','chronic absenteeism'
  ),
  JSON_ARRAY('student','school','calendar_date','attendance_event','attendance_status'),
  JSON_ARRAY(
    'attendance_date','attendance_status','attendance_code',
    'excused','unexcused','tardy','minutes_present','minutes_absent','school_year'
  ),
  JSON_ARRAY('attendance_rate','absences_count','tardies_count','chronic_absent_flag'),
  JSON_ARRAY(
    JSON_OBJECT('term','chronic absenteeism','means',JSON_ARRAY('chronic absence','high absence rate')),
    JSON_OBJECT('term','absence','means',JSON_ARRAY('absent','not present'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','ADA','expansion','Average Daily Attendance')
  ),
  'Event-level and aggregated attendance measures.',
  'Domain: Attendance
Kind: Attendance
Description: Student attendance events and attendance metrics.

Purpose: Track daily attendance, absences, tardies, excused/unexcused status, and chronic absenteeism.

Keywords: attendance, daily attendance, absences, tardies, present, excused, unexcused, chronic absenteeism.
Entities: student, school, calendar_date, attendance_event, attendance_status.
Attributes: attendance_date, attendance_status, attendance_code, excused, unexcused, tardy, minutes_present, minutes_absent, school_year.
Metrics: attendance_rate, absences_count, tardies_count, chronic_absent_flag.
Acronyms: ADA = Average Daily Attendance.
Synonyms: chronic absenteeism = chronic absence.

Excludes: enrollment history, grades/transcripts, assessments, discipline.',
  SHA2(
    'Domain: Attendance
Kind: Attendance
Description: Student attendance events and attendance metrics.

Purpose: Track daily attendance, absences, tardies, excused/unexcused status, and chronic absenteeism.

Keywords: attendance, daily attendance, absences, tardies, present, excused, unexcused, chronic absenteeism.
Entities: student, school, calendar_date, attendance_event, attendance_status.
Attributes: attendance_date, attendance_status, attendance_code, excused, unexcused, tardy, minutes_present, minutes_absent, school_year.
Metrics: attendance_rate, absences_count, tardies_count, chronic_absent_flag.
Acronyms: ADA = Average Daily Attendance.
Synonyms: chronic absenteeism = chronic absence.

Excludes: enrollment history, grades/transcripts, assessments, discipline.',
    256
  )
),

/* ============================================================
   9) Course & Rostering
   ============================================================ */
(
  '927164193773577',
  9,
  'Course catalog, sections, class scheduling, and student rosters.',
  JSON_ARRAY(
    'courses','course catalog','sections','class sections','rostering','rosters',
    'master schedule','class schedule','period','meeting time','room'
  ),
  JSON_ARRAY('course','section','student','staff','school','term','schedule'),
  JSON_ARRAY(
    'course_id','course_code','course_title','course_description',
    'section_id','section_identifier','school_id','term_id','school_year',
    'period','meeting_time','room','start_date','end_date'
  ),
  JSON_ARRAY('section_size','roster_count'),
  JSON_ARRAY(
    JSON_OBJECT('term','roster','means',JSON_ARRAY('class list','section enrollment')),
    JSON_OBJECT('term','section','means',JSON_ARRAY('class section','course section'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','LMS','expansion','Learning Management System')
  ),
  'Connects students and staff to instructional sections and the course catalog.',
  'Domain: Course & Rostering
Kind: Course
Description: Course catalog, sections, class scheduling, and student rosters.

Purpose: Define courses and sections (master schedule), when/where they meet, and which students are rostered in each section.

Keywords: course catalog, courses, sections, class schedule, master schedule, period, room, rosters, rostering.
Entities: course, section, student, staff, school, term, schedule.
Attributes: course_id, course_code, course_title, course_description, section_id, section_identifier, school_id, term_id, school_year, period, meeting_time, room, start_date, end_date.
Metrics: section_size, roster_count.
Synonyms: roster = class list; section = class section.

Excludes: attendance events, discipline incidents, assessment results.',
  SHA2(
    'Domain: Course & Rostering
Kind: Course
Description: Course catalog, sections, class scheduling, and student rosters.

Purpose: Define courses and sections (master schedule), when/where they meet, and which students are rostered in each section.

Keywords: course catalog, courses, sections, class schedule, master schedule, period, room, rosters, rostering.
Entities: course, section, student, staff, school, term, schedule.
Attributes: course_id, course_code, course_title, course_description, section_id, section_identifier, school_id, term_id, school_year, period, meeting_time, room, start_date, end_date.
Metrics: section_size, roster_count.
Synonyms: roster = class list; section = class section.

Excludes: attendance events, discipline incidents, assessment results.',
    256
  )
),

/* ============================================================
   10) Grades, GPA & Transcripts
   ============================================================ */
(
  '927164193773577',
  10,
  'Academic outcomes: course grades, GPA calculations, credits earned, and transcript records.',
  JSON_ARRAY(
    'grades','course grades','report card','grading period','final grade',
    'gpa','grade point average','transcript','credits','credits earned','class rank'
  ),
  JSON_ARRAY('student','course','section','grading_period','transcript','school'),
  JSON_ARRAY(
    'grade_id','student_id','course_id','section_id','school_year',
    'grading_period','term','letter_grade','numeric_grade',
    'gpa','weighted_gpa','credits_attempted','credits_earned','grade_level'
  ),
  JSON_ARRAY('gpa','weighted_gpa','credits_earned_total','credits_attempted_total'),
  JSON_ARRAY(
    JSON_OBJECT('term','report card','means',JSON_ARRAY('grade report','marking period grades')),
    JSON_OBJECT('term','transcript','means',JSON_ARRAY('final transcript','academic record'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','GPA','expansion','Grade Point Average')
  ),
  'Covers outcomes and performance, not attendance or behavior.',
  'Domain: Grades, GPA & Transcripts
Kind: Grades
Description: Academic outcomes and performance.

Purpose: Store course grades by grading period/term, calculate GPA, track credits earned/attempted, and support transcript reporting.

Keywords: grades, course grades, report card, grading period, final grade, GPA, transcript, credits.
Entities: student, course, section, grading_period, transcript, school.
Attributes: grade_id, student_id, course_id, section_id, school_year, grading_period, term, letter_grade, numeric_grade, gpa, weighted_gpa, credits_attempted, credits_earned, grade_level.
Metrics: gpa, weighted_gpa, credits_earned_total, credits_attempted_total.
Acronyms: GPA = Grade Point Average.
Synonyms: report card = grade report; transcript = academic record.

Excludes: attendance events, discipline incidents, assessment results.',
  SHA2(
    'Domain: Grades, GPA & Transcripts
Kind: Grades
Description: Academic outcomes and performance.

Purpose: Store course grades by grading period/term, calculate GPA, track credits earned/attempted, and support transcript reporting.

Keywords: grades, course grades, report card, grading period, final grade, GPA, transcript, credits.
Entities: student, course, section, grading_period, transcript, school.
Attributes: grade_id, student_id, course_id, section_id, school_year, grading_period, term, letter_grade, numeric_grade, gpa, weighted_gpa, credits_attempted, credits_earned, grade_level.
Metrics: gpa, weighted_gpa, credits_earned_total, credits_attempted_total.
Acronyms: GPA = Grade Point Average.
Synonyms: report card = grade report; transcript = academic record.

Excludes: attendance events, discipline incidents, assessment results.',
    256
  )
),

/* ============================================================
   11) Assessments
   ============================================================ */
(
  '927164193773577',
  11,
  'Assessments, objectives/standards, administrations, and student results/scores.',
  JSON_ARRAY(
    'assessments','tests','test scores','student results','benchmark',
    'state assessment','proficiency','performance level','objectives','standards','subscores'
  ),
  JSON_ARRAY('assessment','objective','standard','administration','student','school','subject'),
  JSON_ARRAY(
    'assessment_id','assessment_name','assessment_type',
    'administration_date','school_year','subject','grade_level',
    'score','scaled_score','raw_score','performance_level',
    'objective','standard'
  ),
  JSON_ARRAY('proficiency_rate','average_score','growth_measure'),
  JSON_ARRAY(
    JSON_OBJECT('term','test','means',JSON_ARRAY('assessment','exam')),
    JSON_OBJECT('term','benchmark','means',JSON_ARRAY('interim assessment','diagnostic'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','EOC','expansion','End of Course'),
    JSON_OBJECT('abbr','IRT','expansion','Item Response Theory')
  ),
  'Assessment definitions + student outcomes; often grouped by subject, grade, administration window.',
  'Domain: Assessments
Kind: Assessments
Description: Assessments, objectives, and student results.

Purpose: Store assessment definitions (tests), objectives/standards, administrations, and student results including scores and performance levels.

Keywords: assessments, tests, test scores, benchmark, state assessment, proficiency, performance level, objectives, standards.
Entities: assessment, objective, standard, administration, student, school, subject.
Attributes: assessment_id, assessment_name, assessment_type, administration_date, school_year, subject, grade_level, score, scaled_score, raw_score, performance_level, objective, standard.
Metrics: proficiency_rate, average_score, growth_measure.
Acronyms: EOC = End of Course; IRT = Item Response Theory.
Synonyms: test = assessment; benchmark = interim assessment.

Excludes: attendance events, grades/transcripts, discipline incidents.',
  SHA2(
    'Domain: Assessments
Kind: Assessments
Description: Assessments, objectives, and student results.

Purpose: Store assessment definitions (tests), objectives/standards, administrations, and student results including scores and performance levels.

Keywords: assessments, tests, test scores, benchmark, state assessment, proficiency, performance level, objectives, standards.
Entities: assessment, objective, standard, administration, student, school, subject.
Attributes: assessment_id, assessment_name, assessment_type, administration_date, school_year, subject, grade_level, score, scaled_score, raw_score, performance_level, objective, standard.
Metrics: proficiency_rate, average_score, growth_measure.
Acronyms: EOC = End of Course; IRT = Item Response Theory.
Synonyms: test = assessment; benchmark = interim assessment.

Excludes: attendance events, grades/transcripts, discipline incidents.',
    256
  )
),

/* ============================================================
   12) Discipline
   ============================================================ */
(
  '927164193773577',
  12,
  'Discipline incidents, behaviors, actions, and consequences (referrals, suspensions, expulsions).',
  JSON_ARRAY(
    'discipline','behavior','incidents','referrals','office referral',
    'suspension','in-school suspension','out-of-school suspension','expulsion',
    'consequence','action','infraction'
  ),
  JSON_ARRAY('discipline_incident','behavior','action','student','school','staff','location'),
  JSON_ARRAY(
    'incident_id','student_id','school_id','incident_date',
    'incident_type','behavior_code','location',
    'action_type','action_start_date','action_end_date','duration_days',
    'reporting_category'
  ),
  JSON_ARRAY('incident_count','suspension_days','expulsion_count'),
  JSON_ARRAY(
    JSON_OBJECT('term','referral','means',JSON_ARRAY('discipline referral','office referral')),
    JSON_OBJECT('term','oss','means',JSON_ARRAY('out-of-school suspension'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','ISS','expansion','In-School Suspension'),
    JSON_OBJECT('abbr','OSS','expansion','Out-of-School Suspension')
  ),
  'Captures behavior incidents and disciplinary actions; grouped by school, incident type, time window.',
  'Domain: Discipline
Kind: Discipline
Description: Discipline incidents, behaviors, and actions.

Purpose: Track discipline incidents/behaviors and resulting actions (referrals, suspensions, expulsions), including dates, location, and duration.

Keywords: discipline, behavior, incidents, referrals, suspension, expulsion, consequence.
Entities: discipline_incident, behavior, action, student, school, staff, location.
Attributes: incident_id, student_id, school_id, incident_date, incident_type, behavior_code, location, action_type, action_start_date, action_end_date, duration_days, reporting_category.
Metrics: incident_count, suspension_days, expulsion_count.
Acronyms: ISS = In-School Suspension; OSS = Out-of-School Suspension.
Synonyms: referral = office referral; OSS = out-of-school suspension.

Excludes: attendance events, grades/transcripts, assessment scores.',
  SHA2(
    'Domain: Discipline
Kind: Discipline
Description: Discipline incidents, behaviors, and actions.

Purpose: Track discipline incidents/behaviors and resulting actions (referrals, suspensions, expulsions), including dates, location, and duration.

Keywords: discipline, behavior, incidents, referrals, suspension, expulsion, consequence.
Entities: discipline_incident, behavior, action, student, school, staff, location.
Attributes: incident_id, student_id, school_id, incident_date, incident_type, behavior_code, location, action_type, action_start_date, action_end_date, duration_days, reporting_category.
Metrics: incident_count, suspension_days, expulsion_count.
Acronyms: ISS = In-School Suspension; OSS = Out-of-School Suspension.
Synonyms: referral = office referral; OSS = out-of-school suspension.

Excludes: attendance events, grades/transcripts, assessment scores.',
    256
  )
),

/* ============================================================
   13) Program & Services
   ============================================================ */
(
  '927164193773577',
  13,
  'Student participation in educational programs and services (eligibility, participation windows, service delivery).',
  JSON_ARRAY(
    'programs','services','student programs','program participation',
    'special education','504','english learner','gifted','interventions',
    'supports','accommodations','service delivery'
  ),
  JSON_ARRAY('program','service','participation','student','school','provider'),
  JSON_ARRAY(
    'program_id','program_name','program_type',
    'student_id','school_id',
    'eligibility_status','participation_status',
    'begin_date','end_date','reason','served_minutes'
  ),
  JSON_ARRAY('participants_count','service_minutes_total'),
  JSON_ARRAY(
    JSON_OBJECT('term','sped','means',JSON_ARRAY('special education','special ed')),
    JSON_OBJECT('term','ell','means',JSON_ARRAY('english learner')),
    JSON_OBJECT('term','504','means',JSON_ARRAY('section 504'))
  ),
  JSON_ARRAY(
    JSON_OBJECT('abbr','IEP','expansion','Individualized Education Program'),
    JSON_OBJECT('abbr','EL','expansion','English Learner'),
    JSON_OBJECT('abbr','ELL','expansion','English Language Learner'),
    JSON_OBJECT('abbr','GT','expansion','Gifted and Talented')
  ),
  'Program eligibility and participation; often used with demographics, enrollment, and outcomes.',
  'Domain: Program & Services
Kind: Programs
Description: Student participation in educational programs and services.

Purpose: Track eligibility and participation in programs/services (special education, 504, English learner, gifted, interventions), including start/end dates and service delivery details.

Keywords: programs, services, program participation, special education, 504, english learner, gifted, interventions, accommodations, supports.
Entities: program, service, participation, student, school, provider.
Attributes: program_id, program_name, program_type, student_id, school_id, eligibility_status, participation_status, begin_date, end_date, reason, served_minutes.
Metrics: participants_count, service_minutes_total.
Acronyms: IEP, EL, ELL, GT.
Synonyms: sped = special education; 504 = section 504.

Excludes: discipline incidents; assessment scores (unless explicitly referenced as outcomes).',
  SHA2(
    'Domain: Program & Services
Kind: Programs
Description: Student participation in educational programs and services.

Purpose: Track eligibility and participation in programs/services (special education, 504, English learner, gifted, interventions), including start/end dates and service delivery details.

Keywords: programs, services, program participation, special education, 504, english learner, gifted, interventions, accommodations, supports.
Entities: program, service, participation, student, school, provider.
Attributes: program_id, program_name, program_type, student_id, school_id, eligibility_status, participation_status, begin_date, end_date, reason, served_minutes.
Metrics: participants_count, service_minutes_total.
Acronyms: IEP, EL, ELL, GT.
Synonyms: sped = special education; 504 = section 504.

Excludes: discipline incidents; assessment scores (unless explicitly referenced as outcomes).',
    256
  )
),

/* ============================================================
   14) Calendars & Academic Time
   ============================================================ */
(
  '927164193773577',
  14,
  'School calendars, grading periods, terms/semesters, and instructional time definitions used to time-bound other domains.',
  JSON_ARRAY(
    'calendar','school calendar','academic calendar','school year','term','semester',
    'grading period','marking period','instructional day','holiday','session'
  ),
  JSON_ARRAY('school_calendar','calendar_date','term','semester','grading_period','session','school'),
  JSON_ARRAY(
    'school_year','calendar_date','day_type',
    'term_id','term_name','term_begin_date','term_end_date',
    'grading_period_id','grading_period_name','grading_period_begin_date','grading_period_end_date',
    'is_instructional_day','is_holiday','school_id'
  ),
  JSON_ARRAY('instructional_days','days_in_term','days_in_grading_period'),
  JSON_ARRAY(
    JSON_OBJECT('term','marking period','means',JSON_ARRAY('grading period')),
    JSON_OBJECT('term','academic year','means',JSON_ARRAY('school year'))
  ),
  JSON_ARRAY(),
  'Defines time windows (school years, terms, grading periods) and calendar-day attributes.',
  'Domain: Calendars & Academic Time
Kind: Calendars
Description: School calendars, grading periods, and instructional time.

Purpose: Define school years, terms/semesters, grading periods, sessions, and calendar-day attributes (instructional day, holiday). Used to time-bound enrollment, attendance, grades, and assessments.

Keywords: calendar, school calendar, academic calendar, school year, term, semester, grading period, instructional day, holiday, session.
Entities: school_calendar, calendar_date, term, semester, grading_period, session, school.
Attributes: school_year, calendar_date, day_type, term_id, term_name, term_begin_date, term_end_date, grading_period_id, grading_period_name, grading_period_begin_date, grading_period_end_date, is_instructional_day, is_holiday, school_id.
Metrics: instructional_days, days_in_term, days_in_grading_period.
Synonyms: marking period = grading period; academic year = school year.

Excludes: student demographics, staff assignments, discipline incidents.',
  SHA2(
    'Domain: Calendars & Academic Time
Kind: Calendars
Description: School calendars, grading periods, and instructional time.

Purpose: Define school years, terms/semesters, grading periods, sessions, and calendar-day attributes (instructional day, holiday). Used to time-bound enrollment, attendance, grades, and assessments.

Keywords: calendar, school calendar, academic calendar, school year, term, semester, grading period, instructional day, holiday, session.
Entities: school_calendar, calendar_date, term, semester, grading_period, session, school.
Attributes: school_year, calendar_date, day_type, term_id, term_name, term_begin_date, term_end_date, grading_period_id, grading_period_name, grading_period_begin_date, grading_period_end_date, is_instructional_day, is_holiday, school_id.
Metrics: instructional_days, days_in_term, days_in_grading_period.
Synonyms: marking period = grading period; academic year = school year.

Excludes: student demographics, staff assignments, discipline incidents.',
    256
  )
)

ON DUPLICATE KEY UPDATE
  summary        = VALUES(summary),
  keywords       = VALUES(keywords),
  entities       = VALUES(entities),
  attributes     = VALUES(attributes),
  metrics        = VALUES(metrics),
  synonyms       = VALUES(synonyms),
  acronyms       = VALUES(acronyms),
  notes          = VALUES(notes),
  embedding_text = VALUES(embedding_text),
  content_hash   = VALUES(content_hash),
  updated_at     = CURRENT_TIMESTAMP;