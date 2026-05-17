from flask import Blueprint, render_template, request, after_this_request, send_file, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from .auth import technician_required, admin_required
from .votix import DatabaseHandler
from .crypto import generate_rsa_keys, decrypt_ballot
from ..models import User, Voter, Candidate, Role
from .. import db

import os
import uuid
import logging


admin = Blueprint('admin', __name__)

admin_logger = logging.getLogger(__name__)
admin_logger.setLevel(logging.INFO)
handler = logging.FileHandler('./app/logs/admin.log')
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
admin_logger.addHandler(handler)


@admin.route('/dashboard', methods=['GET', 'POST'])
@login_required
@technician_required
def dashboard():
    with DatabaseHandler('app/var/db.sqlite') as db:
        voters = db.count_voters()[0]
        candidates = db.get_candidates()
        votes = db.count_votes()[0]

    return render_template('dashboard.html', voters=voters, candidates=candidates, votes=votes)


@admin.route('/arm', methods=['GET', 'POST'])
@login_required
@admin_required
def arm():
    if request.method == 'POST':
        passphrase = uuid.uuid4().hex
        pubkey_pem, encrypted_privkey = generate_rsa_keys(passphrase)

        with open('app/var/pubkey.pem', 'wb') as f:
            f.write(pubkey_pem)

        with open('app/var/privkey.pem', 'wb') as f:
            f.write(encrypted_privkey)

        admin_logger.info('Arm successful')
        return render_template('arm.html', passphrase=passphrase)
    else:
        return render_template('arm.html')


@admin.route('/download-key', methods=['POST'])
@login_required
@admin_required
def download_key():
    @after_this_request
    def remove_privkey(response):
        os.remove('app/var/privkey.pem')
        return response

    admin_logger.info('Downloaded private key')
    return send_file('var/privkey.pem', as_attachment=True)


@admin.route('/deliberate', methods=['GET', 'POST'])
@login_required
@admin_required
def deliberate():
    if request.method == 'POST':
        passphrase = request.form['password']

        file = request.files['file']
        if file.filename == '':
            flash('Aucun fichier sélectionné.', 'danger')
            return render_template('no_stress.html')

        if file:
            try:
                filename = uuid.uuid4()
                filepath = os.path.join(current_app.config['FILE_UPLOADS'], f'{filename}.pem')
                file.save(filepath)
                with open(filepath, 'r') as f:
                    privkey = f.read().encode()
            except Exception:
                flash('Fichier invalide.', 'danger')
                return render_template('no_stress.html')

            with DatabaseHandler('app/var/db.sqlite') as db:
                votes = db.get_votes()
                roles = db.get_roles()
                candidates = db.get_candidates()

            # candidate tuple: (id, name, eligible, logo, role_id)
            # Build role-keyed results structure
            role_names = {r[0]: r[1] for r in roles}
            results = {}  # role_id -> {role_name, candidates: {candidate_id -> {name, eligible, votes}}}
            for c in candidates:
                cid, cname, celigible = c[0], c[1], bool(c[2])
                crole_id = c[4] if len(c) > 4 else None
                if crole_id is not None:
                    if crole_id not in results:
                        results[crole_id] = {
                            'role_name': role_names.get(crole_id, f'Rôle #{crole_id}'),
                            'candidates': {}
                        }
                    results[crole_id]['candidates'][cid] = {'name': cname, 'eligible': celigible, 'votes': 0}

            for vote in votes:
                try:
                    encrypted_ballot = hex(int.from_bytes(vote[0], 'big'))[2:]
                    ballot = decrypt_ballot(bytes.fromhex(encrypted_ballot), privkey, passphrase)
                    ballot_data, _voter_uuid = ballot.rsplit('/', 1)
                    if ':' in ballot_data:
                        # Multi-role format: "role_id:candidate_id,..."
                        for choice in ballot_data.split(','):
                            rid_str, cid_str = choice.split(':')
                            rid, cid = int(rid_str), int(cid_str)
                            if rid in results and cid in results[rid]['candidates']:
                                results[rid]['candidates'][cid]['votes'] += 1
                except Exception as e:
                    admin_logger.warning(f"Failed to decrypt a ballot: {e}")
                    continue

            os.remove(filepath)

            # Convert to ordered list for template
            results_by_role = []
            for rid in sorted(results.keys(), key=lambda r: next(
                    (i for i, ro in enumerate(roles) if ro[0] == r), 999)):
                role_entry = results[rid]
                sorted_candidates = sorted(
                    role_entry['candidates'].values(),
                    key=lambda c: -c['votes']
                )
                results_by_role.append({
                    'role_name': role_entry['role_name'],
                    'candidates': sorted_candidates
                })

            admin_logger.info('Deliberation successful')
            flash('Délibération effectuée avec succès.', 'success')
            return render_template('no_stress.html', results_by_role=results_by_role)
    else:
        return render_template('no_stress.html')


@admin.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role     = request.form.get('role', '')

        if not all([username, email, password, role]):
            flash('Tous les champs sont obligatoires.', 'danger')
            return redirect(url_for('admin.users'))

        if role not in ('admin', 'technician'):
            flash('Rôle invalide.', 'danger')
            return redirect(url_for('admin.users'))

        if User.query.filter_by(email=email).first():
            flash('Un utilisateur avec cet email existe déjà.', 'danger')
            return redirect(url_for('admin.users'))

        new_user = User(
            username=username,
            email=email,
            password=generate_password_hash(password, method='scrypt'),
            role=role,
        )
        db.session.add(new_user)
        db.session.commit()
        admin_logger.info(f"User created: {email} ({role})")
        flash(f'Utilisateur {username} créé avec succès.', 'success')
        return redirect(url_for('admin.users'))

    all_users = User.query.order_by(User.role, User.username).all()
    return render_template('users.html', users=all_users)


@admin.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if current_user.id == user_id:
        flash('Vous ne pouvez pas supprimer votre propre compte.', 'danger')
        return redirect(url_for('admin.users'))

    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    admin_logger.info(f"User deleted: {user.email}")
    flash(f'Utilisateur {user.username} supprimé.', 'success')
    return redirect(url_for('admin.users'))


@admin.route('/reset', methods=['POST'])
@login_required
@admin_required
def reset():
    first_admin = User.query.filter_by(role='admin').order_by(User.id).first()

    Voter.query.delete()
    Candidate.query.delete()
    Role.query.delete()
    User.query.filter(User.id != first_admin.id).delete()
    db.session.commit()

    for key_file in ('app/var/pubkey.pem', 'app/var/privkey.pem'):
        try:
            os.remove(key_file)
        except FileNotFoundError:
            pass

    admin_logger.info(f"Application reset by {current_user.email} — first admin kept: {first_admin.email}")
    flash('Application réinitialisée. Électeurs, candidats, rôles et comptes secondaires supprimés.', 'success')
    return redirect(url_for('admin.dashboard'))
