'''
Generate Conference Badges
==========================

Nearly all of the code in this was written by Richard Jones for the 2016 conference.
That code relied on the user supplying the attendee data in a CSV file, which Richard's
code then processed.

The main (and perhaps only real) difference, here, is that the attendee data are taken
directly from the database.  No CSV file is required.

This is now a library with functions / classes referenced by the generate_badges
management command, and by the tickets/badger and tickets/badge API functions.
'''
import sys
import os
import csv
from lxml import etree
import tempfile
from copy import deepcopy
import subprocess

import pdb

from django.core.management.base import BaseCommand

from django.contrib.auth.models import User, Group
from pinaxcon.registrasion.models import AttendeeProfile
from registrasion.controllers.cart import CartController
from registrasion.controllers.invoice import InvoiceController
from registrasion.models import Voucher
from registrasion.models import Attendee
from registrasion.models import Product
from registrasion.models import Invoice
from symposion.speakers.models import Speaker

# A few unicode encodings ...
GLYPH_PLUS = '+'
GLYPH_GLASS = u'\ue001'
GLYPH_DINNER = u'\ue179'
GLYPH_SPEAKER = u'\ue122'
GLYPH_SPRINTS = u'\ue254'
GLYPH_CROWN = u'\ue211'
GLYPH_SNOWMAN = u'\u2603'
GLYPH_STAR = u'\ue007'
GLYPH_FLASH = u'\ue162'
GLYPH_EDU = u'\ue233'

# Some company names are too long to fit on the badge, so, we
# define abbreviations here.
overrides = {
 "Optiver Pty. Ltd.": "Optiver",
 "IRESS Market Tech": "IRESS",
 "The Bureau of Meteorology": "BoM",
 "Google Australia": "Google",
 "Facebook Inc.": "Facebook",
 "Rhapsody Solutions Pty Ltd": "Rhapsody Solutions",
 "PivotNine Pty Ltd": "PivotNine",
 "SEEK Ltd.": "SEEK",
 "UNSW Australia": "UNSW",
 "Dev Demand Co": "Dev Demand",
 "Cascode Labs Pty Ltd": "Cascode Labs",
 "CyberHound Pty Ltd": "CyberHound",
 "Self employed Contractor": "",
 "Data Processors Pty Lmt": "Data Processors",
 "Bureau of Meterology": "BoM",
 "Google Australia Pty Ltd": "Google",
 # "NSW Rural Doctors Network": "",
 "Sense of Security Pty Ltd": "Sense of Security",
 "Hewlett Packard Enterprose": "HPE",
 "Hewlett Packard Enterprise": "HPE",
 "CISCO SYSTEMS INDIA PVT LTD": "CISCO",
 "The University of Melbourne": "University of Melbourne",
 "Peter MacCallum Cancer Centre": "Peter Mac",
 "Commonwealth Bank of Australia": "CBA",
 "VLSCI, University of Melbourne": "VLSCI",
 "Australian Bureau of Meteorology": "BoM",
 "Bureau of Meteorology": "BoM",
 "Australian Synchrotron | ANSTO": "Australian Synchrotron",
 "Bureau of Meteorology, Australia": "BoM",
 "QUT Digital Media Research Centre": "QUT",
 "Dyn - Dynamic Network Services Inc": "Dyn",
 "The Australian National University": "ANU",
 "Murdoch Childrens Research Institute": "MCRI",
 "Centenary Institute, University of Sydney": "Centenary Institute",
 "Synchrotron Light Source Australia Pty Ltd": "Australian Synchrotron",
 "Australian Communication and Media Authority": "ACMA",
 "Dept. of Education - Camden Haven High School": "Camden Haven High School",
 "Australian Government - Bureau of Meteorology": "BoM",
 "The Walter and Eliza Hall Institute of Medical Research": "WEHI",
 "Dept. Parliamentary Services, Australian Parliamentary Library": "Dept. Parliamentary Services",
}


def text_size(text, prev=9999):
    '''
    Calculate the length of a text string as it relates to font size.
    '''
    n = len(text)
    size = int(min(48, max(28, 28 + 30 * (1 - (n-8) / 11.))))
    return min(prev, size)


def set_text(soup, text_id, text, resize=None):
    '''
    Set the text value of an element (via beautiful soup calls).
    '''
    elem = soup.find(".//*[@id='%s']/{http://www.w3.org/2000/svg}tspan" % text_id)
    if elem is None:
        raise ValueError('could not find tag id=%s' % text_id)
    elem.text = text
    if resize:
        style = elem.get('style')
        elem.set('style', style.replace('font-size:60px', 'font-size:%dpx' % resize))


def set_colour(soup, slice_id, colour):
    '''
    Set colour of an element (using beautiful soup calls).
    '''
    elem = soup.find(".//*[@id='%s']" % slice_id)
    if elem is None:
        raise ValueError('could not find tag id=%s' % slice_id)
    style = elem.get('style')
    elem.set('style', style.replace('fill:#316a9a', 'fill:#%s' % colour))

Volunteers = Group.objects.filter(name='Conference volunteers').first().user_set.all()
Organisers = Group.objects.filter(name='Conference organisers').first().user_set.all()

def is_volunteer(attendee):
    '''
    Returns True if attendee is in the Conference volunteers group.
    False otherwise.
    '''
    return attendee.user in Volunteers

def is_organiser(attendee):
    '''
    Returns True if attendee is in the Conference volunteers group.
    False otherwise.
    '''
    return attendee.user in Organisers


def svg_badge(soup, data, n):
    '''
    Do the actual "heavy lifting" to create the badge SVG
    '''
    side = 'lr'[n]
    for tb in 'tb':
        part = tb + side
        lines = [data['firstname'], data['lastname']]
        if data['promote_company']:
            lines.append(data['company'])
        lines.extend([data['line1'], data['line2']])
        lines = filter(None, lines)[:4]

        lines.extend('' for n in range(4-len(lines)))
        prev = 9999
        for m, line in enumerate(lines):
            size = text_size(line, prev)
            set_text(soup, 'line-%s-%s' % (part, m), line, size)
            prev = size

        lines = []
        if data['organiser']:
            lines.append('Organiser')
            set_colour(soup, 'colour-' + part, '319a51')
        elif data['volunteer']:
            lines.append('Volunteer')
            set_colour(soup, 'colour-' + part, '319a51')
        if data['speaker']:
            lines.append('Speaker')

        special = bool(lines)

        if 'Friday Only' in data['ticket']:
            # lines.append('Friday Only')
            set_colour(soup, 'colour-' + part, 'a83f3f')

        if 'Contributor' in data['ticket']:
            lines.append('Contributor')
        elif 'Professional' in data['ticket'] and not data['organiser']:
            lines.append('Professional')
        elif 'Sponsor' in data['ticket'] and not data['organiser']:
            lines.append('Sponsor')
        elif 'Enthusiast' in data['ticket'] and not data['organiser']:
            lines.append('Enthusiast')
        elif data['ticket'] == 'Speaker' and not data['speaker']:
            lines.append('Speaker')
        elif not special:
            if data['ticket']:
                lines.append(data['ticket'])
            elif data['friday']:
                lines.append('Friday Only')
                set_colour(soup, 'colour-' + part, 'a83f3f')
            else:
                lines.append('Tutorial Only')
                set_colour(soup, 'colour-' + part, 'a83f3f')

        if data['friday'] and data['ticket'] and not data['organiser']:
            lines.append('Fri, Sat and Sun')
            if not data['volunteer']:
                set_colour(soup, 'colour-' + part, '71319a')

        if len(lines) > 3:
            raise ValueError('lines = %s' % (lines,))

        for n in range(3 - len(lines)):
            lines.insert(0, '')
        for m, line in enumerate(lines):
            size = text_size(line)
            set_text(soup, 'tags-%s-%s' % (part, m), line, size)

        icons = []
        if data['sprints']:
            icons.append(GLYPH_SPRINTS)
        if data['tutorial']:
            icons.append(GLYPH_EDU)

        set_text(soup, 'icons-' + part, ' '.join(icons))
        set_text(soup, 'shirt-' + side, '; '.join(data['shirts']))
        set_text(soup, 'email-' + side, data['email'])


def collate(options):
    # If specific usernames were given on the command line, just use those.
    # Otherwise, use the entire list of attendees.
    users = User.objects.filter(invoice__status=Invoice.STATUS_PAID)
    if options['usernames']:
        users = users.filter(username__in=options['usernames'])

    # Iterate through the attendee list to generate the badges.
    for n, user in enumerate(users.distinct()):
        ap = user.attendee.attendeeprofilebase.attendeeprofile
        data = dict()

        at_nm = ap.name.split()
        if at_nm[0].lower() in 'mr dr ms mrs miss'.split():
            at_nm[0] = at_nm[0] + ' ' + at_nm[1]
            del at_nm[1]
        if at_nm:
            data['firstname'] = at_nm[0]
            data['lastname'] = ' '.join(at_nm[1:])
        else:
            print ("ERROR:", ap.attendee.user, 'has no name')
            continue

        data['line1'] = ap.free_text_1
        data['line2'] = ap.free_text_2

        data['email'] = user.email
        data['over18'] = ap.of_legal_age
        speaker = Speaker.objects.filter(user=user).first()
        if speaker is None:
            data['speaker'] = False
        else:
            data['speaker'] = bool(speaker.proposals.filter(result__status='accepted'))

        data['paid'] = data['friday'] = data['sprints'] = data['tutorial'] = False
        data['shirts'] = []
        data['ticket'] = ''

        # look over all the invoices, yes
        for inv in Invoice.objects.filter(user_id=ap.attendee.user.id):
            if not inv.is_paid:
                continue
            cart = inv.cart
            if cart is None:
                continue
            data['paid'] = True
            if cart.productitem_set.filter(product__category__name__startswith="Specialist Day").exists():
                data['friday'] = True
            if cart.productitem_set.filter(product__category__name__startswith="Sprint Ticket").exists():
                data['sprints'] = True
            if cart.productitem_set.filter(product__category__name__contains="Tutorial").exists():
                data['tutorial'] = True
            t = cart.productitem_set.filter(product__category__name__startswith="Conference Ticket")
            if t.exists():
                product = t.first().product.name
                if 'SOLD OUT' not in product:
                    data['ticket'] = product
            elif cart.productitem_set.filter(product__category__name__contains="Specialist Day Only").exists():
                data['ticket'] = 'Specialist Day Only'

            data['shirts'].extend(ts.product.name for ts in cart.productitem_set.filter(
                product__category__name__startswith="T-Shirt"))

        if not data['paid']:
            print ("INFO:", ap.attendee.user, 'not paid!')
            continue

        if not data['ticket'] and not (data['friday'] or data['tutorial']):
            print ("ERROR:", ap.attendee.user, 'no conference ticket!')
            continue

        data['company'] = overrides.get(ap.company, ap.company).strip()

        data['volunteer'] = is_volunteer(ap.attendee)
        data['organiser'] = is_organiser(ap.attendee)

        if 'Specialist Day Only' in data['ticket']:
            data['ticket'] = 'Friday Only'

        if 'Conference Organiser' in data['ticket']:
            data['ticket'] = ''

        if 'Conference Volunteer' in data['ticket']:
            data['ticket'] = ''

        data['promote_company'] = (
            data['organiser'] or data['volunteer'] or data['speaker'] or
            'Sponsor' in data['ticket'] or
            'Contributor' in data['ticket'] or
            'Professional' in data['ticket']
        )

        yield data


def generate_stats(options):
    stats = {
        'firstname': [],
        'lastname': [],
        'company': [],
    }
    for badge in collate(options):
        stats['firstname'].append((len(badge['firstname']), badge['firstname']))
        stats['lastname'].append((len(badge['lastname']), badge['lastname']))
        if badge['promote_company']:
            stats['company'].append((len(badge['company']), badge['company']))

    stats['firstname'].sort()
    stats['lastname'].sort()
    stats['company'].sort()

    for l, s in stats['firstname']:
        print ('%2d %s' % (l, s))
    for l, s in stats['lastname']:
        print ('%2d %s' % (l, s))
    for l, s in stats['company']:
        print ('%2d %s' % (l, s))


def generate_badges(options):
    names = list()

    orig = etree.parse(options['template'])
    tree = deepcopy(orig)
    root = tree.getroot()

    for n, data in enumerate(collate(options)):
        svg_badge(root, data, n % 2)
        if n % 2:
            name = os.path.abspath(
                os.path.join(options['out_dir'], 'badge-%d.svg' % n))
            tree.write(name)
            names.append(name)
            tree = deepcopy(orig)
            root = tree.getroot()

    if not n % 2:
        name = os.path.abspath(
            os.path.join(options['out_dir'], 'badge-%d.svg' % n))
        tree.write(name)
        names.append(name)

    return 0

class InvalidTicketChoiceError(Exception):
    '''
    Exception thrown when they chosen ticket isn't valid.  This
    happens either if the ticket choice is 0 (default: Chose a ticket),
    or is greater than the index if the last ticket choice in the
    dropdown list.
    '''
    def __init__(self, message="Please choose a VALID ticket."):
        super(InvalidTicketChoiceError, self).__init__(message,)
