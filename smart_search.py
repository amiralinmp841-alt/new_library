from rapidfuzz import fuzz
import re

import re

MEDICAL_SYNONYMS = {
    # =========================
    # علوم پایه پزشکی
    # =========================
    "آناتومی": "علوم تشریح",
    "اناتومی": "علوم تشریح",
    "انتاتومی": "علوم تشریح",
    "تشریح": "علوم تشریح",
    "علوم تشریح": "علوم تشریح",
    "anatomy": "علوم تشریح",
    "gross anatomy": "علوم تشریح",
    "human anatomy": "علوم تشریح",
    "anat": "علوم تشریح",

    "فیزیولوژی": "فیزیولوژی",
    "فیزیولوژی": "فیزیولوژی",
    "فیزیو": "فیزیولوژی",
    "physiology": "فیزیولوژی",
    "physio": "فیزیولوژی",

    "هیستولوژی": "هیستولوژی",
    "هیستو": "هیستولوژی",
    "بافت": "هیستولوژی",
    "بافت شناسی": "هیستولوژی",
    "histology": "هیستولوژی",
    "histo": "هیستولوژی",
    "microscopic anatomy": "هیستولوژی",

    "امبریولوژی": "امبریولوژی",
    "جنین شناسی": "امبریولوژی",
    "جنین": "امبریولوژی",
    "embryology": "امبریولوژی",
    "embryo": "امبریولوژی",

    "بیوشیمی": "بیوشیمی",
    "بیو شیمی": "بیوشیمی",
    "biochemistry": "بیوشیمی",
    "biochem": "بیوشیمی",

    "ژنتیک": "ژنتیک",
    "ژنتیک پزشکی": "ژنتیک",
    "genetics": "ژنتیک",
    "medical genetics": "ژنتیک",
    "genetic": "ژنتیک",

    "ایمونولوژی": "ایمونولوژی",
    "ایمنی": "ایمونولوژی",
    "ایمنی شناسی": "ایمونولوژی",
    "immunology": "ایمونولوژی",
    "immuno": "ایمونولوژی",

    "میکروب شناسی": "میکروب شناسی",
    "میکروبیولوژی": "میکروب شناسی",
    "میکروب": "میکروب شناسی",
    "microbiology": "میکروب شناسی",
    "micro": "میکروب شناسی",

    "ویروس شناسی": "ویروس شناسی",
    "ویروس": "ویروس شناسی",
    "ویروس شناسی پزشکی": "ویروس شناسی",
    "virology": "ویروس شناسی",
    "virus": "ویروس شناسی",

    "باکتری شناسی": "باکتری شناسی",
    "باکتری": "باکتری شناسی",
    "bacteriology": "باکتری شناسی",
    "bacteria": "باکتری شناسی",

    "انگل شناسی": "انگل شناسی",
    "انگل": "انگل شناسی",
    "پارازیتولوژی": "انگل شناسی",
    "parasitology": "انگل شناسی",
    "parasite": "انگل شناسی",

    "قارچ شناسی": "مایکولوژی",
    "مایکولوژی": "مایکولوژی",
    "قارچ": "مایکولوژی",
    "fungus": "مایکولوژی",
    "fungal": "مایکولوژی",
    "mycology": "مایکولوژی",

    "پاتولوژی": "پاتولوژی",
    "پاتو": "پاتولوژی",
    "آسیب شناسی": "پاتولوژی",
    "pathology": "پاتولوژی",
    "patho": "پاتولوژی",

    "پاتولوژی عمومی": "پاتولوژی عمومی",
    "جنرال پاتولوژی": "پاتولوژی عمومی",
    "general pathology": "پاتولوژی عمومی",

    "پاتولوژی سیستمیک": "پاتولوژی سیستمیک",
    "systemic pathology": "پاتولوژی سیستمیک",
    "system pathology": "پاتولوژی سیستمیک",

    "فارماکولوژی": "فارماکولوژی",
    "فارما": "فارماکولوژی",
    "داروشناسی": "فارماکولوژی",
    "دارو": "فارماکولوژی",
    "pharmacology": "فارماکولوژی",
    "pharma": "فارماکولوژی",

    "اپیدمیولوژی": "اپیدمیولوژی",
    "اپیدمی": "اپیدمیولوژی",
    "epidemiology": "اپیدمیولوژی",
    "epi": "اپیدمیولوژی",

    "آمار زیستی": "آمار زیستی",
    "بیواستات": "آمار زیستی",
    "بیواستاتیستیک": "آمار زیستی",
    "biostatistics": "آمار زیستی",
    "biostat": "آمار زیستی",

    "بهداشت": "بهداشت",
    "بهداشت عمومی": "بهداشت",
    "سلامت عمومی": "بهداشت",
    "public health": "بهداشت",
    "community health": "بهداشت",

    "اخلاق پزشکی": "اخلاق پزشکی",
    "medical ethics": "اخلاق پزشکی",
    "ethics": "اخلاق پزشکی",

    "انفورماتیک پزشکی": "انفورماتیک پزشکی",
    "اطلاعات پزشکی": "انفورماتیک پزشکی",
    "medical informatics": "انفورماتیک پزشکی",

    # =========================
    # علوم پیش‌بالینی / پاراکلینیک
    # =========================
    "هماتولوژی": "هماتولوژی",
    "خون": "هماتولوژی",
    "hematology": "هماتولوژی",
    "heme": "هماتولوژی",

    "ایمونوهِماتولوژی": "ایمونوهِماتولوژی",
    "ایمونوهِماتولوژی": "ایمونوهِماتولوژی",
    "بانک خون": "ایمونوهِماتولوژی",
    "blood bank": "ایمونوهِماتولوژی",

    "رادیولوژی": "رادیولوژی",
    "رادیو": "رادیولوژی",
    "تصویربرداری": "رادیولوژی",
    "imaging": "رادیولوژی",
    "radiology": "رادیولوژی",

    "سونوگرافی": "سونوگرافی",
    "سونو": "سونوگرافی",
    "ultrasound": "سونوگرافی",
    "sonography": "سونوگرافی",

    "سی تی": "سی تی اسکن",
    "سی تی اسکن": "سی تی اسکن",
    "ct": "سی تی اسکن",
    "ct scan": "سی تی اسکن",

    "ام ار ای": "ام آر آی",
    "ام آر آی": "ام آر آی",
    "mri": "ام آر آی",

    "پزشکی هسته ای": "پزشکی هسته ای",
    "nuclear medicine": "پزشکی هسته ای",

    "رادیوتراپی": "رادیوتراپی",
    "پرتودرمانی": "رادیوتراپی",
    "radiotherapy": "رادیوتراپی",

    "آزمایشگاه": "علوم آزمایشگاهی",
    "علوم آزمایشگاهی": "علوم آزمایشگاهی",
    "lab": "علوم آزمایشگاهی",
    "laboratory": "علوم آزمایشگاهی",

    "پاتولوژی بالینی": "پاتولوژی بالینی",
    "clinical pathology": "پاتولوژی بالینی",

    "هیستوپاتولوژی": "هیستوپاتولوژی",
    "بافت پاتولوژی": "هیستوپاتولوژی",
    "histopathology": "هیستوپاتولوژی",
    "surgical pathology": "هیستوپاتولوژی",

    "سیتولوژی": "سیتولوژی",
    "cytology": "سیتولوژی",

    "پاپ اسمیر": "سیتولوژی",
    "pap smear": "سیتولوژی",

    "پزشکی قانونی": "پزشکی قانونی",
    "forensic medicine": "پزشکی قانونی",

    # =========================
    # علوم بالینی / کورها
    # =========================
    "داخلی": "بیماری های داخلی",
    "بیماری داخلی": "بیماری های داخلی",
    "بیماری های داخلی": "بیماری های داخلی",
    "internal": "بیماری های داخلی",
    "internal medicine": "بیماری های داخلی",
    "im": "بیماری های داخلی",

    "جراحی": "جراحی",
    "surgery": "جراحی",
    "general surgery": "جراحی",
    "سرجری": "جراحی",

    "اطفال": "کودکان",
    "کودکان": "کودکان",
    "پدیاتری": "کودکان",
    "اطفال پزشکی": "کودکان",
    "pediatrics": "کودکان",
    "pediatric": "کودکان",
    "peds": "کودکان",

    "زنان": "زنان و زایمان",
    "زنان و زایمان": "زنان و زایمان",
    "مامایی": "زنان و زایمان",
    "gynecology": "زنان و زایمان",
    "obstetrics": "زنان و زایمان",
    "obgyn": "زنان و زایمان",
    "ob gyn": "زنان و زایمان",
    "obs gyn": "زنان و زایمان",

    "اورژانس": "طب اورژانس",
    "طب اورژانس": "طب اورژانس",
    "emergency": "طب اورژانس",
    "emergency medicine": "طب اورژانس",
    "er": "طب اورژانس",

    "هوشبری": "بیهوشی",
    "بیهوشی": "بیهوشی",
    "anesthesiology": "بیهوشی",
    "anesthesia": "بیهوشی",

    "روانپزشکی": "روانپزشکی",
    "روان": "روانپزشکی",
    "سایک": "روانپزشکی",
    "psychiatry": "روانپزشکی",
    "psych": "روانپزشکی",

    "نورولوژی": "نورولوژی",
    "اعصاب": "نورولوژی",
    "مغز و اعصاب": "نورولوژی",
    "neurology": "نورولوژی",
    "neuro": "نورولوژی",

    "جراحی مغز و اعصاب": "جراحی مغز و اعصاب",
    "نوروسرجری": "جراحی مغز و اعصاب",
    "neurosurgery": "جراحی مغز و اعصاب",

    "قلب": "قلب",
    "قلب و عروق": "قلب",
    "کاردیولوژی": "قلب",
    "cardiology": "قلب",
    "cardio": "قلب",

    "جراحی قلب": "جراحی قلب",
    "cardiac surgery": "جراحی قلب",
    "cardiothoracic surgery": "جراحی قلب",

    "ریه": "ریه",
    "پولمونولوژی": "ریه",
    "pulmonary": "ریه",
    "pulmonology": "ریه",
    "chest": "ریه",

    "گوارش": "گوارش",
    "گاسترو": "گوارش",
    "دستگاه گوارش": "گوارش",
    "gastroenterology": "گوارش",
    "gi": "گوارش",

    "کبد": "کبد",
    "هپاتولوژی": "کبد",
    "hepatology": "کبد",

    "کلیه": "نفرولوژی",
    "نفرولوژی": "نفرولوژی",
    "nefro": "نفرولوژی",
    "nephrology": "نفرولوژی",

    "اورولوژی": "اورولوژی",
    "uro": "اورولوژی",
    "urology": "اورولوژی",

    "غدد": "غدد",
    "اندو": "غدد",
    "اندوکرین": "غدد",
    "endocrinology": "غدد",
    "endocrine": "غدد",

    "روماتولوژی": "روماتولوژی",
    "روماتیسم": "روماتولوژی",
    "rheumatology": "روماتولوژی",

    "عفونی": "بیماری های عفونی",
    "بیماری های عفونی": "بیماری های عفونی",
    "infectious": "بیماری های عفونی",
    "infectious disease": "بیماری های عفونی",
    "id": "بیماری های عفونی",

    "انکولوژی": "انکولوژی",
    "oncology": "انکولوژی",
    "cancer": "انکولوژی",

    "هماتولوژی انکولوژی": "هماتولوژی انکولوژی",
    "hemato oncology": "هماتولوژی انکولوژی",
    "hematology oncology": "هماتولوژی انکولوژی",

    "پوست": "درماتولوژی",
    "درم": "درماتولوژی",
    "درماتولوژی": "درماتولوژی",
    "dermatology": "درماتولوژی",
    "derm": "درماتولوژی",

    "چشم": "چشم پزشکی",
    "چشم پزشکی": "چشم پزشکی",
    "افتالمولوژی": "چشم پزشکی",
    "ophthalmology": "چشم پزشکی",
    "ophtha": "چشم پزشکی",
    "ophto": "چشم پزشکی",

    "گوش": "گوش حلق بینی",
    "گوش حلق بینی": "گوش حلق بینی",
    "otolaryngology": "گوش حلق بینی",
    "ent": "گوش حلق بینی",
    "otorhinolaryngology": "گوش حلق بینی",

    "ارتوپدی": "ارتوپدی",
    "ارتو": "ارتوپدی",
    "orthopedics": "ارتوپدی",
    "orthopaedics": "ارتوپدی",
    "ortho": "ارتوپدی",

    "طب فیزیکی": "طب فیزیکی و توانبخشی",
    "فیزیاتری": "طب فیزیکی و توانبخشی",
    "توانبخشی": "طب فیزیکی و توانبخشی",
    "pmr": "طب فیزیکی و توانبخشی",
    "physical medicine": "طب فیزیکی و توانبخشی",
    "rehabilitation": "طب فیزیکی و توانبخشی",

    "طب کار": "طب کار",
    "occupational medicine": "طب کار",

    "طب ورزشی": "طب ورزشی",
    "sports medicine": "طب ورزشی",

    "طب سالمندی": "طب سالمندی",
    "geriatrics": "طب سالمندی",
    "geriatric": "طب سالمندی",

    "طب خانواده": "طب خانواده",
    "family medicine": "طب خانواده",

    "طب تسکینی": "طب تسکینی",
    "palliative care": "طب تسکینی",

    "مراقبت ویژه": "مراقبت ویژه",
    "icu": "مراقبت ویژه",
    "critical care": "مراقبت ویژه",

    "نوزادان": "نوزادان",
    "نئو": "نوزادان",
    "neonatology": "نوزادان",
    "nicu": "نوزادان",

    # =========================
    # اصطلاحات آموزشی / منابع
    # =========================
    "جزوه": "جزوه",
    "جزوه درسی": "جزوه",
    "note": "جزوه",
    "notes": "جزوه",
    "handout": "جزوه",

    "اسلاید": "پاور",
    "اسلایدها": "پاور",
    "پاور": "پاور",
    "پاورپوینت": "پاور",
    "powerpoint": "پاور",
    "slide": "پاور",
    "slides": "پاور",
    "ppt": "پاور",
    "pptx": "پاور",

    "کتاب": "کتاب",
    "رفرنس": "کتاب",
    "مرجع": "کتاب",
    "reference": "کتاب",
    "book": "کتاب",
    "textbook": "کتاب",

    "مقاله": "مقاله",
    "article": "مقاله",
    "paper": "مقاله",
    "journal": "مقاله",

    "سوال": "سوال",
    "نمونه سوال": "سوال",
    "آزمون": "سوال",
    "امتحان": "سوال",
    "تست": "سوال",
    "quiz": "سوال",
    "exam": "سوال",
    "mcq": "سوال",
    "question": "سوال",
    "questions": "سوال",

    "پاسخنامه": "پاسخنامه",
    "answer key": "پاسخنامه",
    "answers": "پاسخنامه",

    "کلاس": "جلسه",
    "جلسه": "جلسه",
    "session": "جلسه",
    "lecture": "جلسه",
    "class": "جلسه",

    "صدا": "صدا",
    "وویس": "صدا",
    "ویس": "صدا",
    "voice": "صدا",
    "audio": "صدا",
    "فایل صوتی": "صدا",
    "mp3": "صدا",
    "wav": "صدا",

    "ویدیو": "ویدیو",
    "ویدئو": "ویدیو",
    "فیلم": "ویدیو",
    "video": "ویدیو",
    "mp4": "ویدیو",
    "movie": "ویدیو",

    "pdf": "pdf",
    "پی دی اف": "pdf",
    "پی‌دی‌اف": "pdf",

    "ورد": "word",
    "word": "word",
    "doc": "word",
    "docx": "word",

    "اکسل": "excel",
    "excel": "excel",
    "xls": "excel",
    "xlsx": "excel",

    "تصویر": "تصویر",
    "عکس": "تصویر",
    "image": "تصویر",
    "photo": "تصویر",
    "jpg": "تصویر",
    "jpeg": "تصویر",
    "png": "تصویر",

    # =========================
    # اصطلاحات دوره/مرحله آموزشی
    # =========================
    "علوم پایه": "علوم پایه",
    "پایه": "علوم پایه",
    "basic sciences": "علوم پایه",

    "فیزیوپات": "فیزیوپاتولوژی",
    "فیزیوپاتولوژی": "فیزیوپاتولوژی",
    "pathophysiology": "فیزیوپاتولوژی",

    "استاجری": "استاژری",
    "استاژری": "استاژری",
    "externship": "استاژری",

    "اینترنی": "اینترنی",
    "internship": "اینترنی",

    "رزیدنتی": "رزیدنتی",
    "دستیاری": "رزیدنتی",
    "residency": "رزیدنتی",
    "resident": "رزیدنتی",

    "فلوشیپ": "فلوشیپ",
    "fellowship": "فلوشیپ",

    # =========================
    # اصطلاحات پاتولوژی/میکرو/قارچ که به درد شما می‌خورند
    # =========================
    "میکوز": "عفونت قارچی",
    "fungal infection": "عفونت قارچی",
    "قارچی": "عفونت قارچی",

    "موکور": "موکورمایکوزیس",
    "موکورمایکوز": "موکورمایکوزیس",
    "موکورمایکوزیس": "موکورمایکوزیس",
    "mucor": "موکورمایکوزیس",
    "mucormycosis": "موکورمایکوزیس",
    "zygomycosis": "موکورمایکوزیس",

    "کریپتو": "کریپتوکوکوزیس",
    "کریپتوکوک": "کریپتوکوکوزیس",
    "کریپتوکوکوز": "کریپتوکوکوزیس",
    "کریپتوکوکوزیس": "کریپتوکوکوزیس",
    "cryptococcus": "کریپتوکوکوزیس",
    "cryptococcosis": "کریپتوکوکوزیس",

    "کاندیدا": "کاندیدیازیس",
    "کاندید": "کاندیدیازیس",
    "کاندیدیاز": "کاندیدیازیس",
    "کاندیدیازیس": "کاندیدیازیس",
    "candida": "کاندیدیازیس",
    "candidiasis": "کاندیدیازیس",

    "آسپرژیلوس": "آسپرژیلوزیس",
    "آسپرژیل": "آسپرژیلوزیس",
    "آسپرژیلوز": "آسپرژیلوزیس",
    "آسپرژیلوزیس": "آسپرژیلوزیس",
    "aspergillus": "آسپرژیلوزیس",
    "aspergillosis": "آسپرژیلوزیس",

    "اسپوروتریکوز": "اسپوروتریکوزیس",
    "اسپوروتریکوزیس": "اسپوروتریکوزیس",
    "sporotrichosis": "اسپوروتریکوزیس",
    "sporothrix": "اسپوروتریکوزیس",

    "موسی کارمین": "موسیکارمین",
    "موسیکارمین": "موسیکارمین",
    "mucicarmine": "موسیکارمین",

    "ایندیا اینک": "ایندیا اینک",
    "india ink": "ایندیا اینک",

    "آلشیان بلو": "آلشیان بلو",
    "alcian blue": "آلشیان بلو",

    "chlamydospore": "کلامیدوسپور",
    "کلامیدوسپور": "کلامیدوسپور",
    "کلامیدوسپور تست": "تست کلامیدوسپور",

    "germ tube": "تست ژرم تیوب",
    "ژرم تیوب": "تست ژرم تیوب",
    "germ tube test": "تست ژرم تیوب",

    "hyphae": "هیف",
    "hypha": "هیف",
    "هیف": "هیف",

    "pseudohypha": "پسودوهیف",
    "pseudohyphae": "پسودوهیف",
    "پسودوهیف": "پسودوهیف",

    "yeast": "مخمر",
    "مخمر": "مخمر",

    "capsule": "کپسول",
    "کپسول": "کپسول",

    "budding": "جوانه زنی",
    "جوانه زنی": "جوانه زنی",

    "septate": "سپتادار",
    "سپتادار": "سپتادار",

    "aseptate": "غیرسپتادار",
    "nonseptate": "غیرسپتادار",
    "غیر سپتادار": "غیرسپتادار",
    "غیرسپتادار": "غیرسپتادار",

    "acute angle": "زاویه حاد",
    "زاویه حاد": "زاویه حاد",

    "right angle": "زاویه قائمه",
    "زاویه قائمه": "زاویه قائمه",

    "broad based": "پهن",
    "broad": "پهن",

    # =========================
    # استین/رنگ‌آمیزی/آزمایش
    # =========================
    "pas": "PAS",
    "پی ای اس": "PAS",
    "periodic acid schiff": "PAS",

    "gms": "GMS",
    "gomori methenamine silver": "GMS",
    "گوموری": "GMS",
    "سیلور stain": "GMS",

    "h e": "H&E",
    "he": "H&E",
    "h&e": "H&E",
    "هماتوکسیلین ائوزین": "H&E",

    "zifn": "زیل نیلسن",
    "ziehl neelsen": "زیل نیلسن",
    "زیل نیلسن": "زیل نیلسن",

    "گرام": "رنگ آمیزی گرم",
    "گرم": "رنگ آمیزی گرم",
    "gram": "رنگ آمیزی گرم",
    "gram stain": "رنگ آمیزی گرم",

    # =========================
    # نمونه‌ها / specimen
    # =========================
    "نمونه": "نمونه",
    "specimen": "نمونه",
    "sample": "نمونه",

    "بیوپسی": "بیوپسی",
    "biopsy": "بیوپسی",

    "رزکشن": "رزکسیون",
    "رزکسیون": "رزکسیون",
    "resection": "رزکسیون",

    "اسلاید شیشه": "لام",
    "لام": "لام",
    "slide glass": "لام",

    "بلوک": "بلوک پارافین",
    "پارافین بلوک": "بلوک پارافین",
    "block": "بلوک پارافین",
    "ffpe": "بلوک پارافین",

    # =========================
    # ارگان‌ها
    # =========================
    "ریه ها": "ریه",
    "lung": "ریه",
    "lungs": "ریه",

    "قلبی": "قلب",
    "heart": "قلب",

    "کبدی": "کبد",
    "liver": "کبد",

    "کلیوی": "کلیه",
    "kidney": "کلیه",
    "renal": "کلیه",

    "مغز": "مغز",
    "brain": "مغز",
    "cns": "سیستم عصبی مرکزی",

    "پوستی": "پوست",
    "skin": "پوست",

    "چشمی": "چشم",
    "eye": "چشم",

    # =========================
    # اصطلاحات متفرقه جستجو/مرتب‌سازی
    # =========================
    "فایل": "فایل",
    "document": "فایل",
    "doc": "فایل",

    "جدید": "جدید",
    "new": "جدید",
    "آخرین": "جدید",
    "latest": "جدید",

    "قدیمی": "قدیمی",
    "old": "قدیمی",

    "ترم": "ترم",
    "semester": "ترم",

    "درس": "درس",
    "subject": "درس",
    "course": "درس",

    "استاد": "استاد",
    "professor": "استاد",
    "teacher": "استاد",
    "faculty": "استاد",

    "دانشگاه": "دانشگاه",
    "university": "دانشگاه",

    "بخش": "بخش",
    "rotation": "بخش",
    "ward": "بخش",
}

from rapidfuzz import fuzz
import re


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = str(text)

    replacements = {
        "ي": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "\u200c": " ",
        "‌": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    digit_replacements = {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }

    for old, new in digit_replacements.items():
        text = text.replace(old, new)

    text = text.lower()

    # علائم را فاصله کن
    text = re.sub(r"[^\w\sآ-ی0-9]", " ", text)

    # فاصله اضافه
    text = re.sub(r"\s+", " ", text).strip()

    return text


ORDINAL_REPLACEMENTS = {
    "اول": "1",
    "یک": "1",
    "دوم": "2",
    "دو": "2",
    "سوم": "3",
    "سه": "3",
    "چهارم": "4",
    "چهار": "4",
    "پنجم": "5",
    "پنج": "5",
    "ششم": "6",
    "شش": "6",
    "هفتم": "7",
    "هفت": "7",
    "هشتم": "8",
    "هشت": "8",
    "نهم": "9",
    "نه": "9",
    "دهم": "10",
    "ده": "10",
}


def normalize_ordinals(text: str) -> str:
    """
    تبدیل کلمات عددی به عدد، فقط وقتی کلمه مستقل باشند.
    نسخه قبلی با replace ساده ممکن بود وسط کلمات را خراب کند.
    """
    if not text:
        return ""

    text = normalize_text(text)

    for old, new in sorted(ORDINAL_REPLACEMENTS.items(), key=lambda x: len(x[0]), reverse=True):
        old_norm = normalize_text(old)
        text = re.sub(rf"(?<!\S){re.escape(old_norm)}(?!\S)", new, text)

    text = re.sub(r"\s+", " ", text).strip()
    return text


MEDICAL_SYNONYMS_NORM = None


def build_medical_synonyms_norm():
    global MEDICAL_SYNONYMS_NORM

    if MEDICAL_SYNONYMS_NORM is None:
        MEDICAL_SYNONYMS_NORM = {
            normalize_ordinals(k): normalize_ordinals(v)
            for k, v in MEDICAL_SYNONYMS.items()
        }


def canonicalize_text(text: str) -> str:
    text = normalize_ordinals(text)
    build_medical_synonyms_norm()

    # عبارت‌های بلندتر اول جایگزین شوند
    for key in sorted(MEDICAL_SYNONYMS_NORM.keys(), key=len, reverse=True):
        value = MEDICAL_SYNONYMS_NORM[key]
        text = re.sub(rf"(?<!\S){re.escape(key)}(?!\S)", value, text)

    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str):
    text = canonicalize_text(text)
    if not text:
        return set()

    tokens = set(text.split())

    # توکن‌های خیلی بی‌ارزش را حذف می‌کنیم
    stopwords = {
        "و", "یا", "از", "به", "در", "با", "برای", "را", "که", "این", "اون", "آن",
        "the", "a", "an", "of", "to", "for", "in", "on", "and", "or",
    }

    return {t for t in tokens if len(t) >= 2 and t not in stopwords}


def get_item_search_text(item: dict) -> str:
    """
    متن قابل جستجو از هر آیتم محتوایی.
    اینجا باید هر چیزی که ممکن است اسم یا توضیح فایل باشد خوانده شود.
    """
    if not isinstance(item, dict):
        return ""

    fields = []

    possible_text_keys = [
        # متن و کپشن
        "text",
        "caption",

        # اسم فایل‌های document/video/audio
        "file_name",
        "filename",
        "name",
        "title",

        # بعضی ساختارهای احتمالی
        "original_file_name",
        "original_filename",
        "performer",
        "mime_type",
        "file_unique_id",
    ]

    for key in possible_text_keys:
        value = item.get(key)
        if value:
            fields.append(str(value))

    return " ".join(fields)


def get_content_texts(node):
    """
    متن قابل جستجو از محتواهای یک نود:
    - متن پیام
    - کپشن
    - اسم فایل
    - title فایل صوتی/ویدیویی
    """
    texts = []

    for item in node.get("contents", []):
        item_text = get_item_search_text(item)
        if item_text:
            texts.append(item_text)

    return " ".join(texts)


def build_path_parts(db, node_id):
    """
    ساخت مسیر کامل یک نود بر اساس parent.
    """
    parts = []
    current = node_id

    visited = set()

    while current and current in db and current not in visited:
        visited.add(current)

        if current != "root":
            node_name = db[current].get("name", "")
            if node_name:
                parts.append(node_name)

        current = db[current].get("parent")

    parts.reverse()
    return parts


def flatten_db_for_search(db):
    results = []

    for node_id, node in db.items():
        if node_id == "root":
            continue

        node_name = node.get("name", "")
        path_parts = build_path_parts(db, node_id)
        path_text = " ".join(path_parts)
        contents_text = get_content_texts(node)

        node_name_norm = canonicalize_text(node_name)
        path_text_norm = canonicalize_text(path_text)
        contents_text_norm = canonicalize_text(contents_text)

        all_text_norm = " ".join([
            node_name_norm,
            path_text_norm,
            contents_text_norm,
        ]).strip()

        if not all_text_norm:
            continue

        results.append({
            "node_id": node_id,
            "title": node_name,
            "path": " ⬅️ ".join(path_parts),
            "node_name_text": node_name_norm,
            "path_text": path_text_norm,
            "contents_text": contents_text_norm,
            "search_text": all_text_norm,
        })

    return results


def safe_score(query_norm: str, target_norm: str) -> float:
    """
    امتیاز ترکیبی که اجازه نمی‌دهد partial_ratio به تنهایی همه چیز را 100 کند.
    """
    if not query_norm or not target_norm:
        return 0

    token_set = fuzz.token_set_ratio(query_norm, target_norm)
    token_sort = fuzz.token_sort_ratio(query_norm, target_norm)
    wratio = fuzz.WRatio(query_norm, target_norm)
    partial = fuzz.partial_ratio(query_norm, target_norm)

    # partial روی متن بلند خیلی کاذب 100 می‌دهد؛ پس وزنش کم است.
    score = (
        token_set * 0.40 +
        token_sort * 0.20 +
        wratio * 0.30 +
        partial * 0.10
    )

    return score


def exact_phrase_bonus(query_norm: str, target_norm: str) -> int:
    if not query_norm or not target_norm:
        return 0

    if query_norm == target_norm:
        return 18

    if query_norm in target_norm:
        return 10

    return 0


def token_overlap_score(query_tokens, target_tokens) -> float:
    if not query_tokens or not target_tokens:
        return 0

    matched = query_tokens & target_tokens
    return len(matched) / len(query_tokens)


def smart_search(db, query, limit=10, min_score=45):
    query_norm = canonicalize_text(query)

    if not query_norm:
        return []

    query_tokens = tokenize(query_norm)
    items = flatten_db_for_search(db)

    results = []

    for item in items:
        node_name_text = item["node_name_text"]
        path_text = item["path_text"]
        contents_text = item["contents_text"]
        all_text = item["search_text"]

        all_tokens = tokenize(all_text)
        overlap = token_overlap_score(query_tokens, all_tokens)

        # اگر هیچ توکن واقعی مشترک نیست، فقط با fuzzy خیلی بالا قبولش کن
        # این جلوی نتایج کاذب را می‌گیرد.
        if overlap == 0:
            fuzzy_all = safe_score(query_norm, all_text)
            if fuzzy_all < 75:
                continue

        name_score = safe_score(query_norm, node_name_text)
        path_score = safe_score(query_norm, path_text)
        content_score = safe_score(query_norm, contents_text)
        all_score = safe_score(query_norm, all_text)

        name_bonus = exact_phrase_bonus(query_norm, node_name_text)
        path_bonus = exact_phrase_bonus(query_norm, path_text)
        content_bonus = exact_phrase_bonus(query_norm, contents_text)

        # امتیاز نهایی:
        # اسم خود نود و محتوای خود نود مهم‌تر از مسیر هستند.
        best_field_score = max(
            name_score + name_bonus,
            content_score + content_bonus,
            path_score * 0.85 + path_bonus,
            all_score * 0.90,
        )

        # اگر همه توکن‌های کوئری داخل متن باشند، امتیاز معتبرتر است
        overlap_bonus = overlap * 12

        final_score = best_field_score + overlap_bonus

        # سقف 100
        final_score = min(final_score, 100)

        if final_score >= min_score:
            results.append({
                "node_id": item["node_id"],
                "title": item["title"],
                "path": item["path"],
                "score": final_score,
                "debug": {
                    "name_score": name_score,
                    "path_score": path_score,
                    "content_score": content_score,
                    "all_score": all_score,
                    "overlap": overlap,
                }
            })

    # مرتب‌سازی دقیق‌تر
    # اول امتیاز نهایی، بعد میزان overlap
    results.sort(
        key=lambda x: (
            x["score"],
            x["debug"]["overlap"],
            x["debug"]["content_score"],
            x["debug"]["name_score"],
        ),
        reverse=True
    )

    # debug را از خروجی نهایی حذف می‌کنیم
    cleaned = []
    for r in results[:limit]:
        r.pop("debug", None)
        cleaned.append(r)

    return cleaned
