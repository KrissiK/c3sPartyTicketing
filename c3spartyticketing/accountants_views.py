# -*- coding: utf-8 -*-
import json
from c3spartyticketing.models import (
    PartyTicket,
    C3sStaff,
    DBSession,
)
from c3spartyticketing.utils import (
    make_qr_code_pdf,
    make_random_string,
)
from pkg_resources import resource_filename
import colander
import deform
from deform import ValidationFailure

from pyramid.i18n import (
    get_localizer,
)
from pyramid.request import Request
from pyramid.response import Response
from pyramid.view import view_config
from pyramid.threadlocal import get_current_request
from pyramid.httpexceptions import HTTPFound
from pyramid.security import (
    remember,
    forget,
    authenticated_userid,
)
from pyramid.url import route_url

from pyramid_mailer import get_mailer
from pyramid_mailer.message import Message

from translationstring import TranslationStringFactory
from types import NoneType
from datetime import datetime

deform_templates = resource_filename('deform', 'templates')
c3spartyticketing_templates = resource_filename(
    'c3spartyticketing', 'templates')

my_search_path = (deform_templates, c3spartyticketing_templates)

_ = TranslationStringFactory('c3spartyticketing')


def translator(term):
    return get_localizer(get_current_request()).translate(term)

my_template_dir = resource_filename('c3spartyticketing', 'templates/')
deform_template_dir = resource_filename('deform', 'templates/')

zpt_renderer = deform.ZPTRendererFactory(
    [
        my_template_dir,
        deform_template_dir,
    ],
    translator=translator,
)
# the zpt_renderer above is referred to within the demo.ini file by dotted name

DEBUG = False
LOGGING = True

if LOGGING:  # pragma: no cover
    import logging
    log = logging.getLogger(__name__)


@view_config(renderer='templates/login.pt',
             route_name='login')
def accountants_login(request):
    """
    This view lets accountants log in
    """
    logged_in = authenticated_userid(request)
    #print("authenticated_userid: " + str(logged_in))

    log.info("login by %s" % logged_in)

    if logged_in is not None:  # if user is already authenticated
        return HTTPFound(  # redirect her to the dashboard
            request.route_url('dashboard',
                              number=0,))

    class AccountantLogin(colander.MappingSchema):
        """
        colander schema for login form
        """
        login = colander.SchemaNode(
            colander.String(),
            title=_(u"login"),
            oid="login",
        )
        password = colander.SchemaNode(
            colander.String(),
            validator=colander.Length(min=5, max=100),
            widget=deform.widget.PasswordWidget(size=20),
            title=_(u"password"),
            oid="password",
        )

    schema = AccountantLogin()

    form = deform.Form(
        schema,
        buttons=[
            deform.Button('submit', _(u'Submit')),
            deform.Button('reset', _(u'Reset'))
        ],
        #use_ajax=True,
        #renderer=zpt_renderer
    )

    # if the form has been used and SUBMITTED, check contents
    if 'submit' in request.POST:
        #print("the form was submitted")
        controls = request.POST.items()
        try:
            appstruct = form.validate(controls)
        except ValidationFailure, e:
            print(e)

            request.session.flash(
                _(u"Please note: There were errors, "
                  "please check the form below."),
                'message_above_form',
                allow_duplicate=False)
            return{'form': e.render()}

        # get user and check pw...
        login = appstruct['login']
        password = appstruct['password']

        try:
            checked = C3sStaff.check_password(login, password)
        except AttributeError:  # pragma: no cover
            checked = False
        if checked:
            log.info("password check for %s: good!" % login)
            headers = remember(request, login)
            log.info("logging in %s" % login)
            return HTTPFound(  # redirect to accountants dashboard
                location=route_url(  # after successful login
                    'dashboard',
                    number=0,
                    request=request),
                headers=headers)
        else:
            log.info("password check: failed.")

    html = form.render()
    return {'form': html, }


@view_config(renderer='templates/dashboard.pt',
             permission='manage',
             route_name='dashboard')
def accountants_desk(request):
    """
    This view lets accountants view applications and set their status:
    has their payment arrived?
    """
    #print("who is it? %s" % request.user.login)
    _number_of_datasets = PartyTicket.get_number()
    #print("request.matchdict['number']: %s" % request.matchdict['number'])
    try:  # check if
        # a page number was supplied with the URL
        _page_to_show = int(request.matchdict['number'])
        #print("page to show: %s" % _page_to_show)
    except:
        _page_to_show = 0
    # is it a number? yes, cast above
    #if not isinstance(_page_to_show, type(1)):
    #    _page_to_show = 0
    #print("_page_to_show: %s" % _page_to_show)

    # check for input from "find dataset by confirm code" form
    if 'code_to_show' in request.POST:
        print("found code_to_show in POST: %s" % request.POST['code_to_show'])
        try:
            _code = request.POST['code_to_show']
            #print(_code)
            _entry = PartyTicket.get_by_code(_code)
            print(_entry)
            print(_entry.id)

            return HTTPFound(
                location=request.route_url(
                    'detail',
                    ticket_id=_entry.id)
            )
        except:
            # choose default
            print("barf!")
            pass

    # how many to display on one page?
    """
    num_display determines how many items are to be shown on one page
    """
    #print request.POST
    if 'num_to_show' in request.POST:
        #print("found it in POST")
        try:
            _num = int(request.POST['num_to_show'])
            if isinstance(_num, type(1)):
                num_display = _num
        except:
            # choose default
            num_display = 20
    elif 'num_display' in request.cookies:
        #print("found it in cookie")
        num_display = int(request.cookies['num_display'])
    else:
        #print("setting default")
        num_display = request.registry.settings[
            'c3spartyticketing.dashboard_number']
    #print("num_display: %s " % num_display)

    """
    base_offset helps us to minimize impact on the database
    when querying for results.
    we can choose just those results we need for the page to show
    """
    #try:
    base_offset = int(_page_to_show) * int(num_display)
    #print("base offset: %s" % base_offset)
    #except:
    #    base_offset = 0
    #    if 'base_offset' in request.session:
    #        base_offset = request.session['base_offset']
    #    else:
    #        base_offset = request.registry.settings['speedfunding.offset']

    # get data sets from DB
    _tickets = PartyTicket.ticket_listing(
        PartyTicket.id.desc(), how_many=num_display, offset=base_offset)

    # calculate next-previous-navi
    next_page = (int(_page_to_show) + 1)
    if (int(_page_to_show) > 0):
        previous_page = int(_page_to_show) - 1
    else:
        previous_page = int(_page_to_show)

    # store info about current page in cookie
    request.response.set_cookie('on_page', value=str(_page_to_show))
    #print("num_display: %s" % num_display)
    request.response.set_cookie('num_display', value=str(num_display))

    #
    # prepare the autocomplete form for codes
    #
    # get codes from another view via subrequest, see
    # http://docs.pylonsproject.org/projects/pyramid/en/latest/narr/subrequest.html
    subreq = Request.blank('/all_codes')  # see http://0.0.0.0:6543/all_codes
    response = request.invoke_subrequest(subreq)
    #print("the subrequests response: %s" % response.body)
    #import requests
    #r = requests.get('http://0.0.0.0:6543/all_codes')
    #the_codes = json.loads(r.text)  # gotcha: json needed!
    the_codes = json.loads(response.body)  # gotcha: json needed!

    my_autoc_wid = deform.widget.AutocompleteInputWidget(
        min_length=1,
        title="widget title",
        values=the_codes,
    )

    # prepare a form for autocomplete search for codes.
    class CodeAutocompleteForm(colander.MappingSchema):
        """
        colander schema to make deform autocomplete form
        """
        code_to_show = colander.SchemaNode(
            colander.String(),
            title="Search entry (autocomplete)",
            validator=colander.Length(min=1, max=8),
            widget=my_autoc_wid,
            description='start typing. use arrows. press enter. twice.'

        )

    schema = CodeAutocompleteForm()
    form = deform.Form(
        schema,
        buttons=('go!',),
        #use_ajax=True,  # <-- whoa!
        renderer=zpt_renderer,
    )
    autoformhtml = form.render()

    return {'_number_of_datasets': _number_of_datasets,
            'tickets': _tickets,
            'num_display': num_display,
            'next': next_page,
            'previous': previous_page,
            'autoform': autoformhtml,
            }


@view_config(renderer='templates/stats.pt',
             permission='manage',
             route_name='stats')
def stats_view(request):
    """
    This view lets accountants view statistics:
    how many tickets of which category, payment status, etc.
    """
    #print("who is it? %s" % request.user.login)
    _number_of_datasets = PartyTicket.get_number()
    _number_of_tickets = PartyTicket.get_num_tickets()
    _num_passengers = PartyTicket.num_passengers()
    _num_open_tickets = int(_number_of_tickets) - int(_num_passengers)
    _num_tickets_unpaid = PartyTicket.get_num_unpaid()
    #
    _num_hobos = PartyTicket.get_num_hobos()
    _num_class_2 = PartyTicket.get_num_class_2()
    _num_class_2_food = PartyTicket.get_num_class_2_food()
    _num_class_1 = PartyTicket.get_num_class_1()
    _num_class_green = PartyTicket.get_num_class_green()
    #
    _sum_tickets_total = PartyTicket.get_sum_tickets_total()
    _sum_tickets_paid = PartyTicket.get_sum_tickets_paid()
    _sum_tickets_unpaid = PartyTicket.get_sum_tickets_unpaid()

    return {
        '_number_of_datasets': _number_of_datasets,
        '_number_of_tickets': _number_of_tickets,
        '_num_passengers': _num_passengers,
        '_num_open_tickets': _num_open_tickets,
        '_num_tickets_unpaid': _num_tickets_unpaid,
        # ticket categories
        'num_hobos': _num_hobos,
        'num_class_2': _num_class_2,
        'num_class_2_food': _num_class_2_food,
        'num_class_1': _num_class_1,
        'num_class_green': _num_class_green,
        # focus on cash
        'sum_tickets_total': _sum_tickets_total,
        'sum_tickets_paid': _sum_tickets_paid,
        'sum_tickets_unpaid': _sum_tickets_unpaid,
    }


@view_config(route_name='hobo',
             renderer='templates/new_hobo.pt',
             permission='manage')
def make_hobo_view(request):
    """
    this view adds schwarzfahrers to the gästeliste
    """
    class PersonalData(colander.MappingSchema):
        """
        colander schema for membership application form
        """
        locale_name = 'de'
        firstname = colander.SchemaNode(
            colander.String(),
            title=_(u"Vorame"),
            oid="firstname",
        )
        lastname = colander.SchemaNode(
            colander.String(),
            title=_(u"Nachname"),
            oid="lastname",
        )
        email = colander.SchemaNode(
            colander.String(),
            title=_(u'Email'),
            validator=colander.Email(),
            oid="email",
        )
        comment = colander.SchemaNode(
            colander.String(),
            title=_("Warum Schwarzfahren?"),
            missing='',
            validator=colander.Length(max=250),
            widget=deform.widget.TextAreaWidget(rows=3, cols=50),
            description=_(u"(guter grund) (255 Zeichen)"),
            oid="comment",
        )
        _LOCALE_ = colander.SchemaNode(
            colander.String(),
            widget=deform.widget.HiddenWidget(),
            default=locale_name
        )

    class HoboForm(colander.Schema):
        """
        The Form consists of
        - Personal Data
        - Ticketing Information
        - FoodInfo
        """
        person = PersonalData(
            title=_(u"Persönliche Daten"),
            #description=_(u"this is a test"),
            #css_class="thisisjustatest"
        )

    schema = HoboForm()

    form = deform.Form(
        schema,
        buttons=[
            deform.Button('submit', _(u'Absenden')),
            deform.Button('reset', _(u'Zurücksetzen'))
        ],
        #use_ajax=True,
        renderer=zpt_renderer
    )

    if 'submit' in request.POST:
        print "new hobo!?!"
        controls = request.POST.items()
        try:
            appstruct = form.validate(controls)
            print('validated!')
            the_total = 0  # nothing to pay
            # create an appstruct for persistence
            randomstring = make_random_string()
            hobo = PartyTicket(
                firstname=appstruct['person']['firstname'],
                lastname=appstruct['person']['lastname'],
                email=appstruct['person']['email'],
                password='',  # appstruct['person']['password'],
                locale=appstruct['person']['_LOCALE_'],
                email_is_confirmed=False,
                email_confirm_code=randomstring,
                date_of_submission=datetime.now(),
                num_tickets=1,
                ticket_type=5,
                the_total=the_total,
                user_comment=appstruct['person']['comment'],
            )
            hobo.payment_received = True
            dbsession = DBSession
            #try:
            print "about to add ticket"
            dbsession.add(hobo)
            dbsession.flush()
            print "added ticket"
            #except InvalidRequestError, e:  # pragma: no cover
            #    print("InvalidRequestError! %s") % e
            #except IntegrityError, ie:  # pragma: no cover
            #print("IntegrityError! %s") % ie
            return HTTPFound(
                request.route_url('detail',
                                  ticket_id=hobo.id)
            )

        except ValidationFailure, e:
            return {
                'hoboform': e.render()
            }

    return {'hoboform': form.render()}


@view_config(route_name='send_ticket_mail',
             permission='manage')
def send_ticket_mail_view(request):
    """
    this view sends a mail to the user with ticket links
    """
    _id = request.matchdict['ticket_id']
    _ticket = PartyTicket.get_by_id(_id)
    if isinstance(_ticket, NoneType):
        return HTTPFound(
            request.route_url(
                'dashboard',
                number=request.cookies['on_page'],
                order=request.cookies['order'],
                orderby=request.cookies['orderby'],
            )
        )

    mailer = get_mailer(request)
    body_lines = (  # a list of lines
        u'''Hallo ''', _ticket.firstname, ' ', _ticket.lastname, u''' !

Wir haben Deine Überweisung erhalten. Dankeschön!

Es gibt mehrere Möglichkeiten, das Ticket mitzubringen:

1) Lade jetzt dein Ticket herunter und drucke es aus.
   Wir scannen dann am Eingang den QR-Code und du bist drin.

   ''', request.route_url('get_ticket',
                          email=_ticket.email,
                          code=_ticket.email_confirm_code), u'''

2) Lade die mobile version für dein Smartphone (oder Tablet).

   ''', request.route_url('get_ticket_mobile',
                          email=_ticket.email,
                          code=_ticket.email_confirm_code), u'''

3) Bringe einfach diesen Code mit: ''' + _ticket.email_confirm_code + u'''

Damit können wir dich am Eingang wiedererkennen. Falls Du ein Ticket für
*mehrere Personen* bestellt hast, kannst Du diesen Code an diese Personen
weiterreichen. Aber Vorsicht! Wir zählen mit! ;-)

Bis bald!

Dein C3S-Team''',
    )
    the_mail_body = ''.join([line for line in body_lines])
    the_mail = Message(
        subject=_(u"C3S Party-Ticket: bitte herunterladen!"),
        sender="noreply@c3s.cc",
        recipients=[_ticket.email],
        body=the_mail_body
    )
    from smtplib import SMTPRecipientsRefused
    try:
        #mailer.send(the_mail)
        mailer.send_immediately(the_mail, fail_silently=False)
        #print(the_mail.body)
        _ticket.ticketmail_sent = True
        _ticket.ticketmail_sent_date = datetime.now()

    except SMTPRecipientsRefused:  # folks with newly bought tickets (no mail)
        print('SMTPRecipientsRefused')
        return HTTPFound(
            request.route_url('dashboard', number=request.cookies['on_page'],))

    # 'else': send user to the form
    return HTTPFound(request.route_url('dashboard',
                                       number=request.cookies['on_page'],
                                       #order=request.cookies['order'],
                                       #orderby=request.cookies['orderby'],
                                       )
                     )
#
# @view_config(permission='manage',
#              route_name='mail_pay_confirmation')
# def send_ticket_mail(request):
#     """
#     send a mail to membership applicant
#     informing her about reception of payment
#     """
#     _id = request.matchdict['memberid']
#     _member = C3sMember.get_by_id(_id)

#     message = Message(
#         subject=_('[C3S AFM] We have received your payment. Thanks!'),
#         sender='yes@c3s.cc',
#         recipients=[_member.email],
#         body=make_payment_confirmation_emailbody(_member)
#     )
#     #print(message.body)
#     mailer = get_mailer(request)
#     mailer.send(message)
#     _member.payment_confirmed = True
#     _member.payment_confirmed_date = datetime.now()
#     return HTTPFound(request.route_url('dashboard',
#                                        number=request.cookies['on_page'],
#                                        order=request.cookies['order'],
#                                        orderby=request.cookies['orderby'],
#                                        )
#                      )


@view_config(renderer='templates/.pt',
             permission='manage',
             route_name='give_ticket')
def give_ticket(request):
    """
    this view gives a user access to her ticket via URL with code
    the response is a PDF download
    """
    _code = request.matchdict['code']
    _ticket = PartyTicket.get_by_code(_code)
#    _url = 'https://events.c3s.cc/ci/p1402/' + _ticket.email_confirm_code
#    _url = 'https://192.168.2.128:6544/ci/p1402/' + _ticket.email_confirm_code
    _url = request.registry.settings[
        'c3spartyticketing.url'] + '/ci/p1402/' + _ticket.email_confirm_code
    # return a pdf file
    pdf_file = make_qr_code_pdf(_url)
    response = Response(content_type='application/pdf')
    pdf_file.seek(0)  # rewind to beginning
    response.app_iter = open(pdf_file.name, "r")
    return response

# @view_config(permission='manage',
#              route_name='switch_sig')
# def switch_sig(request):
#     """
#     This view lets accountants switch member signature info
#     has their signature arrived?
#     """
#     memberid = request.matchdict['memberid']
#     #log.info("the id: %s" % memberid)

#     # store the dashboard page the admin came from
#     dashboard_page = request.cookies['on_page']

#     _member = C3sMember.get_by_id(memberid)
#     if _member.signature_received is True:
#         _member.signature_received = False
#         _member.signature_received_date = datetime(1970, 1, 1)
#     elif _member.signature_received is False:
#         _member.signature_received = True
#         _member.signature_received_date = datetime.now()

#     log.info(
#         "signature status of member.id %s changed by %s to %s" % (
#             _member.id,
#             request.user.login,
#             _member.signature_received
#         )
#     )

#     return HTTPFound(
#         request.route_url('dashboard',
#                           number=dashboard_page,))


@view_config(permission='manage',
             route_name='delete_entry')
def delete_entry(request):
    """
    This view lets accountants delete entries (doublettes)
    """
    _id = request.matchdict['ticket_id']
    dashboard_page = request.cookies['on_page']
    _entry = PartyTicket.get_by_id(_id)

    PartyTicket.delete_by_id(_entry.id)
    log.info(
        "entry.id %s was deleted by %s" % (_entry.id,
                                           request.user.login,)
    )
    return HTTPFound(
        request.route_url('dashboard',
                          number=dashboard_page,))


@view_config(permission='manage',
             route_name='switch_pay')
def switch_pay(request):
    """
    This view lets accountants switch member signature info
    has their signature arrived?
    """
    speed_id = request.matchdict['ticket_id']
    dashboard_page = request.cookies['on_page']
    _entry = PartyTicket.get_by_id(speed_id)

    if _entry.payment_received is True:  # change to NOT SET
        _entry.payment_received = False
        _entry.payment_received_date = datetime(1970, 1, 1)
    elif _entry.payment_received is False:  # set to NOW
        _entry.payment_received = True
        _entry.payment_received_date = datetime.now()

#    log.info(
#        "payment info of speedfunding.id %s changed by %s to %s" % (
#            _entry.id,
#            request.user.login,
#            _entry.payment_received
#        )
#    )
    return HTTPFound(
        request.route_url('dashboard',
                          number=dashboard_page,))


@view_config(renderer='templates/detail.pt',
             permission='manage',
             route_name='detail')
def ticket_detail(request):
    """
    This view lets accountants view ticket order details
    how about the payment?
    """
    # check if staffer wanted to look at specific ticket id
    tid = request.matchdict['ticket_id']
    #log.info("the id: %s" % tid)

    _ticket = PartyTicket.get_by_id(tid)

    #print(_speedfunding)
    if _ticket is None:  # that speed_id did not produce good results
        return HTTPFound(  # back to base
            request.route_url('dashboard',
                              number=0,))

    class ChangeDetails(colander.MappingSchema):
        """
        colander schema (form) to change details of speedfunding
        """
        payment_received = colander.SchemaNode(
            colander.Bool(),
            title=_(u"Zahlungseingang melden?")
        )

    schema = ChangeDetails()
    form = deform.Form(
        schema,
        buttons=[
            deform.Button('submit', _(u'Submit')),
            deform.Button('reset', _(u'Reset'))
        ],
        #use_ajax=True,
        #renderer=zpt_renderer
    )

    # if the form has been used and SUBMITTED, check contents
    if 'submit' in request.POST:
        controls = request.POST.items()
        try:
            appstruct = form.validate(controls)
        except ValidationFailure, e:  # pragma: no cover
            log.info(e)
            #print("the appstruct from the form: %s \n") % appstruct
            #for thing in appstruct:
            #    print("the thing: %s") % thing
            #    print("type: %s") % type(thing)
            print(e)
            #message.append(
            request.session.flash(
                _(u"Please note: There were errors, "
                  "please check the form below."),
                'message_above_form',
                allow_duplicate=False)
            return{'form': e.render()}

        # change info about speedfunding in database ?
        same = (  # changed value through form (different from db)?
            appstruct['payment_received'] == _ticket.payment_received)
        if not same:
            log.info(
                "info about payment of %s changed by %s to %s" % (
                    _ticket.id,
                    request.user.login,
                    appstruct['payment_received']))
            _ticket.payment_received = appstruct['payment_received']
            if _ticket.payment_received is True:
                _ticket.payment_received_date = datetime.now()
            else:
                _ticket.payment_received_date = datetime(
                    1970, 1, 1)
        # store appstruct in session
        request.session['appstruct'] = appstruct

        # show the updated details
        HTTPFound(route_url('detail', request, ticket_id=_ticket.id))

    # else: form was not submitted: just show speedfunding info and form
    else:
        appstruct = {  # populate form with values from DB
            #'signature_received': _speedfunding.signature_received,
            'payment_received': _ticket.payment_received}
        form.set_appstruct(appstruct)
        #print("the appstruct: %s") % appstruct
    html = form.render()

    return {'ticket': _ticket,
            'form': html}


@view_config(permission='view',
             route_name='logout')
def logout_view(request):
    """
    can be used to log a user/staffer off. "forget"
    """
    request.session.invalidate()
    request.session.flash(u'Logged out successfully.')
    headers = forget(request)
    return HTTPFound(location=route_url('login', request),
                     headers=headers)


@view_config(renderer='json',
             #permission='manage',  # XXX make this work w/ permission
             route_name='all_codes')
def list_codes(request):
    """
    return the list of codes
    """
    if 'localhost' not in request.host:
        return 'foo'
    codes = PartyTicket.get_all_codes()
    return codes
