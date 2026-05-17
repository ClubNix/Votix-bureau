from flask import Blueprint, render_template, request, flash, current_app, redirect, url_for
from flask_login import login_required
from dotenv import load_dotenv, dotenv_values

from .database import DatabaseHandler
from .mail_sender import validate_email_domain, send_link_email
from .auth import admin_required, technician_required
from ..models import Voter, Candidate, Role
from .crypto import encrypt_ballot

import uuid
import random
import logging
import csv
import os
import time

from PIL import Image


votix = Blueprint('votix', __name__)

load_dotenv(dotenv_path='./app/.env')
_PROMOTION_LIST = os.getenv('PROMOTION_LIST').split(',')

promotion_list = [element for element in _PROMOTION_LIST if element != '']

votix_logger = logging.getLogger(__name__)
votix_logger.setLevel(logging.INFO)
handler = logging.FileHandler('./app/logs/votix.log')
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
votix_logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Voters
# ---------------------------------------------------------------------------

@votix.route('/register-voter', methods=['GET', 'POST'])
@login_required
@technician_required
def register_voter():
    if request.method == 'POST':
        last_name = request.form['last_name'].lower()
        first_name = request.form['first_name'].lower()
        email = request.form['email']
        promotion = request.form['promotion']

        send_email = bool(request.form.get('send_email'))

        if not validate_email_domain(email):
            flash('Adresse email invalide ou domaine non autorisé.', 'danger')
            return render_template('register_voter.html', list=promotion_list)

        with DatabaseHandler('app/var/db.sqlite') as db:
            if db.get_voter_by_email(email) is not None:
                flash('Un électeur avec cette adresse email existe déjà.', 'danger')
                return render_template('register_voter.html', list=promotion_list)

            try:
                link_string = str(uuid.uuid4())
                secret = str(random.randint(0, 9999)).zfill(4)
                db.add_voter(Voter(last_name=last_name, first_name=first_name, email=email, promotion=promotion,
                                   voted=False, link_string=link_string, secret=secret, invitation_sent=False,
                                   link_sent=False))
            except Exception as e:
                flash(f'Une erreur est survenue lors de l\'ajout de l\'électeur : {e}', 'danger')
                return render_template('register_voter.html', list=promotion_list)

        if not send_email:
            flash('Électeur ajouté. Le lien de vote n\'a pas été envoyé.', 'success')
        else:
            try:
                voter_obj = Voter.query.filter_by(email=email).first()
                if voter_obj:
                    send_link_email(voter_obj)
                    flash('Électeur ajouté et lien de vote envoyé avec succès.', 'success')
                else:
                    flash('Électeur ajouté, mais impossible de récupérer le compte pour l\'envoi du lien.', 'warning')
            except Exception as e:
                votix_logger.error(f"Failed to send link email to {email}: {e}")
                flash('Électeur ajouté, mais l\'envoi du lien de vote a échoué.', 'warning')

        return render_template('register_voter.html', list=promotion_list)
    else:
        return render_template('register_voter.html', list=promotion_list)


@votix.route('/import-voters', methods=['GET', 'POST'])
@login_required
@admin_required
def import_voters():
    if request.method == 'POST':
        file = request.files['file']
        if file.filename == '':
            flash('Aucun fichier sélectionné.', 'danger')
            return render_template('import_voters.html', list=promotion_list)

        if file:
            try:
                filepath = os.path.join(current_app.config['FILE_UPLOADS'], f'{uuid.uuid4()}.csv')
                file.save(filepath)
                with DatabaseHandler('app/var/db.sqlite') as db:
                    with open(filepath, 'r') as f:
                        reader = csv.reader(f)
                        next(reader)
                        for row in reader:
                            last_name, first_name, email, promotion = row

                            link_string = str(uuid.uuid4())
                            secret = str(random.randint(0, 9999)).zfill(4)
                            db.add_voter(Voter(
                                last_name=last_name, first_name=first_name, email=email, promotion=promotion,
                                link_string=link_string, secret=secret)
                            )
            except Exception as e:
                flash('Une erreur est survenue lors de l\'importation des électeurs.', 'danger')
                votix_logger.error(f"An error occurred while importing voters: {e}")
                return render_template('import_voters.html', list=promotion_list)

            votix_logger.info('Voters imported successfully via {file.filename}')
            flash('Électeurs importés avec succès.', 'success')
            return render_template('import_voters.html', list=promotion_list)
    else:
        return render_template('import_voters.html', list=promotion_list)


@votix.route('/voters')
@login_required
@technician_required
def voters_list():
    from ..models import Voter as VoterModel
    all_voters = VoterModel.query.order_by(VoterModel.last_name, VoterModel.first_name).all()
    safe_voters = [
        {
            'id':              v.id,
            'last_name':       v.last_name,
            'first_name':      v.first_name,
            'email':           v.email,
            'promotion':       v.promotion,
            'invitation_sent': v.invitation_sent,
            'link_sent':       v.link_sent,
        }
        for v in all_voters
    ]
    return render_template('voters.html', voters=safe_voters)


@votix.route('/voters/<int:voter_id>/send-link', methods=['POST'])
@login_required
@technician_required
def send_voter_link(voter_id):
    from ..models import Voter as VoterModel
    voter = VoterModel.query.get_or_404(voter_id)
    try:
        send_link_email(voter)
        flash(f'Lien de vote envoyé à {voter.email}.', 'success')
    except Exception as e:
        flash(f'Erreur lors de l\'envoi à {voter.email} : {e}', 'danger')
    return redirect(url_for('votix.voters_list'))


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

@votix.route('/roles')
@login_required
@technician_required
def roles():
    with DatabaseHandler('app/var/db.sqlite') as db:
        all_roles = db.get_roles()
        all_candidates = db.get_candidates()
    # Count candidates per role
    candidate_count = {}
    for c in all_candidates:
        rid = c[4] if len(c) > 4 else None
        if rid is not None:
            candidate_count[rid] = candidate_count.get(rid, 0) + 1
    return render_template('roles.html', roles=all_roles, candidate_count=candidate_count)


@votix.route('/register-role', methods=['GET', 'POST'])
@login_required
@technician_required
def register_role():
    if request.method == 'POST':
        name = request.form['name'].strip()
        display_order = int(request.form.get('display_order') or 0)
        if not name:
            flash('Le nom du rôle est requis.', 'danger')
            return render_template('register_role.html')
        try:
            with DatabaseHandler('app/var/db.sqlite') as db:
                db.add_role(name, display_order)
        except Exception as e:
            flash(f'Une erreur est survenue lors de l\'ajout du rôle : {e}', 'danger')
            return render_template('register_role.html')
        flash('Rôle ajouté avec succès.', 'success')
        return redirect(url_for('votix.roles'))
    return render_template('register_role.html')


@votix.route('/edit-role/<int:role_id>', methods=['GET', 'POST'])
@login_required
@technician_required
def edit_role(role_id):
    with DatabaseHandler('app/var/db.sqlite') as db:
        role = db.get_role(role_id)

    if role is None:
        flash('Rôle introuvable.', 'danger')
        return redirect(url_for('votix.roles'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        display_order = int(request.form.get('display_order') or 0)
        if not name:
            flash('Le nom du rôle est requis.', 'danger')
            return render_template('edit_role.html', role=role)
        try:
            with DatabaseHandler('app/var/db.sqlite') as db:
                db.update_role(role_id, name, display_order)
        except Exception as e:
            flash(f'Une erreur est survenue lors de la mise à jour du rôle : {e}', 'danger')
            return render_template('edit_role.html', role=role)
        flash('Rôle mis à jour avec succès.', 'success')
        return redirect(url_for('votix.roles'))

    return render_template('edit_role.html', role=role)


@votix.route('/delete-role/<int:role_id>', methods=['POST'])
@login_required
@technician_required
def delete_role(role_id):
    with DatabaseHandler('app/var/db.sqlite') as db:
        role = db.get_role(role_id)
        if role is None:
            flash('Rôle introuvable.', 'danger')
            return redirect(url_for('votix.roles'))
        db.delete_role(role_id)
    flash('Rôle supprimé.', 'success')
    return redirect(url_for('votix.roles'))


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

@votix.route('/candidates')
@login_required
@technician_required
def candidates():
    with DatabaseHandler('app/var/db.sqlite') as db:
        all_candidates = db.get_candidates_with_role()
    return render_template('candidates.html', candidates=all_candidates)


_ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _allowed_logo(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in _ALLOWED_LOGO_EXTENSIONS


def _save_compressed_logo(file_stream, dest_path: str) -> None:
    img = Image.open(file_stream)
    if img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGBA')
    img.thumbnail((400, 400), Image.LANCZOS)
    img.save(dest_path, format='WEBP', quality=80, method=6)


@votix.route('/register-candidate', methods=['GET', 'POST'])
@login_required
@technician_required
def register_candidate():
    with DatabaseHandler('app/var/db.sqlite') as db:
        all_roles = db.get_roles()

    if request.method == 'POST':
        name = request.form['name']
        role_id_str = request.form.get('role_id')
        role_id = int(role_id_str) if role_id_str else None

        logo_filename = ''
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            if not _allowed_logo(logo_file.filename):
                flash('Format de logo invalide. Utilisez PNG, JPG, JPEG, GIF ou WEBP.', 'danger')
                return render_template('register_candidate.html', roles=all_roles)
            logo_filename = f'{uuid.uuid4()}.webp'
            _save_compressed_logo(logo_file, os.path.join(current_app.config['FILE_UPLOADS'], logo_filename))

        try:
            with DatabaseHandler('app/var/db.sqlite') as db:
                db.add_candidate(Candidate(name=name, logo=logo_filename, role_id=role_id))
        except Exception as e:
            flash(f'Une erreur est survenue lors de l\'ajout du candidat : {e}', 'danger')
            return render_template('register_candidate.html', roles=all_roles)

        flash('Candidat ajouté avec succès.', 'success')
        return redirect(url_for('votix.candidates'))
    else:
        return render_template('register_candidate.html', roles=all_roles)


@votix.route('/edit-candidate/<int:candidate_id>', methods=['GET', 'POST'])
@login_required
@technician_required
def edit_candidate(candidate_id):
    with DatabaseHandler('app/var/db.sqlite') as db:
        candidate = db.get_candidate(candidate_id)
        all_roles = db.get_roles()

    if candidate is None:
        flash('Candidat introuvable.', 'danger')
        return redirect(url_for('votix.candidates'))

    if request.method == 'POST':
        name = request.form['name']
        remove_logo = bool(request.form.get('remove_logo'))
        role_id_str = request.form.get('role_id')
        role_id = int(role_id_str) if role_id_str else None

        current_logo = candidate[3] if len(candidate) > 3 else ''
        logo_filename = current_logo

        if remove_logo:
            if current_logo:
                try:
                    os.remove(os.path.join(current_app.config['FILE_UPLOADS'], current_logo))
                except FileNotFoundError:
                    pass
            logo_filename = ''
        else:
            logo_file = request.files.get('logo')
            if logo_file and logo_file.filename:
                if not _allowed_logo(logo_file.filename):
                    flash('Format de logo invalide. Utilisez PNG, JPG, JPEG, GIF ou WEBP.', 'danger')
                    return render_template('edit_candidate.html', candidate=candidate, roles=all_roles)
                if current_logo:
                    try:
                        os.remove(os.path.join(current_app.config['FILE_UPLOADS'], current_logo))
                    except FileNotFoundError:
                        pass
                logo_filename = f'{uuid.uuid4()}.webp'
                _save_compressed_logo(logo_file, os.path.join(current_app.config['FILE_UPLOADS'], logo_filename))

        with DatabaseHandler('app/var/db.sqlite') as db:
            db.update_candidate(candidate_id, name, logo_filename, role_id)

        flash('Candidat mis à jour avec succès.', 'success')
        return redirect(url_for('votix.candidates'))

    return render_template('edit_candidate.html', candidate=candidate, roles=all_roles)


@votix.route('/delete-candidate/<int:candidate_id>', methods=['POST'])
@login_required
@technician_required
def delete_candidate(candidate_id):
    with DatabaseHandler('app/var/db.sqlite') as db:
        candidate = db.get_candidate(candidate_id)
        if candidate is None:
            flash('Candidat introuvable.', 'danger')
            return redirect(url_for('votix.candidates'))

        logo = candidate[3] if len(candidate) > 3 else ''
        if logo:
            try:
                os.remove(os.path.join(current_app.config['FILE_UPLOADS'], logo))
            except FileNotFoundError:
                pass

        db.delete_candidate(candidate_id)

    flash('Candidat supprimé.', 'success')
    return redirect(url_for('votix.candidates'))


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------

@votix.route('/vote/<link_string>', methods=['GET', 'POST'])
def vote(link_string):
    current_time = int(time.time())
    cfg = dotenv_values('./app/.env')
    voting_start = int(cfg.get('VOTING_START', 0) or 0)
    voting_end   = int(cfg.get('VOTING_END', 0) or 0)

    if current_time < voting_start:
        flash("Le vote n'a pas encore commencé.", 'danger')
        return render_template('index.html')
    if current_time > voting_end:
        flash('Le vote est terminé.', 'danger')
        return render_template('index.html')

    with DatabaseHandler('app/var/db.sqlite') as db:
        voter = db.get_voter_by_link(link_string)
        roles = db.get_roles()
        candidates = db.get_candidates()

        if voter is None:
            flash("Ce lien de vote n'existe pas.", 'danger')
            return render_template('index.html')
        if voter.voted:
            flash('Cet électeur a déjà voté.', 'danger')
            return render_template('index.html')

        # Build per-role candidate lists
        # candidate tuple: (id, name, eligible, logo, role_id)
        role_data = []
        for role in roles:
            role_candidates = [c for c in candidates if len(c) > 4 and c[4] == role[0]]
            if role_candidates:
                role_data.append({'id': role[0], 'name': role[1], 'candidates': role_candidates})

        if request.method == 'POST':
            secret_code = request.form['secret']

            if not secret_code:
                flash('Le code secret est requis.', 'danger')
                return render_template('vote.html', voter=voter, role_data=role_data)
            if voter.secret != secret_code.zfill(4):
                flash('Code secret invalide.', 'danger')
                return render_template('vote.html', voter=voter, role_data=role_data)

            # Collect one candidate per role
            choices = {}
            for role_entry in role_data:
                rid = role_entry['id']
                cid_str = request.form.get(f'role_{rid}')
                if not cid_str:
                    flash(f'Veuillez voter pour le poste : {role_entry["name"]}', 'danger')
                    return render_template('vote.html', voter=voter, role_data=role_data)
                cid = int(cid_str)
                # Verify the candidate is eligible and belongs to this role
                valid = next((c for c in role_entry['candidates'] if c[0] == cid), None)
                if valid is None:
                    flash('Candidat invalide.', 'danger')
                    return render_template('vote.html', voter=voter, role_data=role_data)
                choices[rid] = cid

            if not choices:
                flash('Aucun rôle à voter n\'est configuré.', 'danger')
                return render_template('vote.html', voter=voter, role_data=role_data)

            # Ballot format: "role_id:candidate_id,role_id:candidate_id,.../voter_uuid"
            ballot_data = ','.join(f'{rid}:{cid}' for rid, cid in sorted(choices.items()))

            try:
                pubkey = open('app/var/pubkey.pem', 'rb').read()
                ballot = encrypt_ballot(ballot_data, pubkey, str(voter.link_string))
                db.add_vote(voter, ballot)
            except Exception as e:
                flash(f'Une erreur est survenue lors de l\'enregistrement du vote : {e}', 'danger')
                return render_template('vote.html', voter=voter, role_data=role_data)

        else:
            return render_template('vote.html', voter=voter, role_data=role_data)

    flash('Vote enregistré avec succès.', 'success')
    return render_template('index.html')
